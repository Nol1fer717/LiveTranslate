from collections import deque
import json
import os
import re
import queue
import sys
import threading
from pathlib import Path

import ctranslate2
import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.vad import get_speech_timestamps, get_vad_model
from vosk import KaldiRecognizer


RATE = 16000
FRAME = 512  # Silero's 32 ms analysis window
END_OF_SENTENCE = re.compile(r"""[.!?…]["'»”)]*$""")
REPEATED_NUMBER = re.compile(r"(?<!\d)(\d+)(?:[\s.,;:\-–—]+\1(?!\d)){6,}")
TECHNICAL_TERMS = "SSH, PostgreSQL, Postgres, Nginx, Linux, Docker, Kubernetes, GitHub, SQL, API."
TERM_PATTERNS = [
    (re.compile(r"(?<!\w)(?:ссш|ссн|эс[ -]?эс[ -]?(?:эйч|аш)|ssh)(?!\w)", re.I), "SSH"),
    (re.compile(r"(?<!\w)(?:постгрес(?:с(?:а|у|ом|е)?)?|позгрес(?:с(?:а|у|ом|е)?)?|postgress|postgresql)(?!\w)", re.I), "PostgreSQL"),
    (re.compile(r"(?<!\w)(?:энджинкс(?:а|у|ом|е)?|инжинкс(?:а|у|ом|е)?|nginx)(?!\w)", re.I), "Nginx"),
]
_DLL_DIRECTORIES = []


def normalize_terms(text):
    text = re.sub(r"(?i)(\b(?:доступ|подключени\w*)\s+по\s+)(?:ссс|сс|cc|ccc)(?!\w)", r"\1SSH", text)
    for pattern, canonical in TERM_PATTERNS:
        text = pattern.sub(canonical, text)
    return text


def load_whisper(folder):
    package_root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(sys.prefix) / "Lib" / "site-packages"
    for name in ("cublas", "cudnn", "cuda_nvrtc"):
        directory = package_root / "nvidia" / name / "bin"
        if directory.is_dir():
            _DLL_DIRECTORIES.append(os.add_dll_directory(str(directory)))
            if str(directory) not in os.environ.get("PATH", "").split(os.pathsep):
                os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
    try:
        if ctranslate2.get_cuda_device_count():
            model = WhisperModel(str(folder), device="cuda", compute_type="float16", cpu_threads=3,
                                 num_workers=2, local_files_only=True)
            # Initialize CUDA and cuDNN before capture starts, and verify that inference works.
            list(model.transcribe(np.zeros(RATE, dtype=np.float32), language="ru", beam_size=1)[0])
            return model
    except (RuntimeError, OSError):
        pass
    return WhisperModel(str(folder), device="cpu", compute_type="int8", cpu_threads=3,
                        num_workers=2, local_files_only=True)


def reliable(segment):
    return (segment.no_speech_prob <= 0.65 and segment.avg_logprob >= -1.0
            and segment.compression_ratio <= 2.4 and not REPEATED_NUMBER.search(segment.text))


class SpeechGate:
    """Keep Silero's recurrent state private to each audio device."""
    def __init__(self):
        self.session = get_vad_model().session
        self.reset()

    def reset(self):
        self.h = np.zeros((1, 1, 128), np.float32)
        self.c = np.zeros_like(self.h)
        self.context = np.zeros(64, np.float32)

    def probability(self, frame):
        samples = np.frombuffer(frame, "<i2").astype(np.float32) / 32768
        inputs = np.concatenate((self.context, samples))[None, :]
        self.context = samples[-64:]
        probability, self.h, self.c = self.session.run(None, {"input": inputs, "h": self.h, "c": self.c})
        return float(probability.item()) if np.max(np.abs(samples)) > 0.0003 else 0.0


class WhisperStream:
    """Buffer speech until a pause; retain undecided words across long windows."""
    def __init__(self, model, languages, speaker_model, speakers, line, partial, preview=None):
        self.model = model
        self.languages = languages
        self.speakers = speakers
        self.line = line
        self.partial = partial
        self.speaker_decoder = None
        if speaker_model is not None:
            self.speaker_decoder = KaldiRecognizer(languages["en"].speech, RATE, speaker_model)
        self.gate = SpeechGate()
        self.pending = bytearray()
        self.lead = deque(maxlen=9)
        self.frames = bytearray()
        self.onset = self.quiet = self.voiced = 0
        self.previous_text = ""
        self.previous_language = self.previous_speaker = None
        self.unfinished = ""
        self.last_voice = self.clock = 0
        self.preview = preview
        self.preview_lock = threading.Lock()
        self.preview_generation = 0
        self.preview_at = 0
        self.preview_queue = queue.Queue(maxsize=1)
        self.preview_thread = None
        if preview is not None:
            self.preview_thread = threading.Thread(target=self.run_preview, daemon=True)
            self.preview_thread.start()

    def run_preview(self):
        while True:
            item = self.preview_queue.get()
            if item is None:
                return
            generation, pcm, prefix = item
            try:
                audio = np.frombuffer(pcm, "<i2").astype(np.float32) / 32768
                segments, info = self.model.transcribe(audio, language=None, beam_size=1, temperature=0,
                                                       condition_on_previous_text=False, hotwords=TECHNICAL_TERMS)
                text = " ".join(s.text.strip() for s in segments if reliable(s)).strip()
                if not text or info.language_probability < 0.42 or info.language not in self.languages:
                    continue
                text = normalize_terms((prefix + " " + text).strip())
                translated = self.languages[info.language].translate(text)
                with self.preview_lock:
                    if generation == self.preview_generation:
                        self.preview((text, translated, info.language.upper()))
            except Exception:
                # A preview is optional; the final recognition still reports its own errors.
                continue

    def queue_preview(self):
        if self.preview is None or len(self.frames) < 0.75 * RATE * 2 or self.clock - self.preview_at < 0.75 * RATE:
            return
        self.preview_at = self.clock
        with self.preview_lock:
            item = (self.preview_generation, bytes(self.frames), self.unfinished)
        try:
            self.preview_queue.put_nowait(item)
        except queue.Full:
            try:
                self.preview_queue.get_nowait()
                self.preview_queue.put_nowait(item)
            except (queue.Empty, queue.Full):
                pass

    def clear_preview(self, hide=True):
        if self.preview is not None:
            with self.preview_lock:
                self.preview_generation += 1
                if hide:
                    self.preview(None)

    def close(self):
        if self.preview_thread is not None:
            self.clear_preview()
            try:
                self.preview_queue.get_nowait()
            except queue.Empty:
                pass
            self.preview_queue.put(None)
            self.preview_thread.join()

    def accept(self, pcm):
        self.pending.extend(pcm)
        while len(self.pending) >= FRAME * 2:
            frame = bytes(self.pending[:FRAME * 2])
            del self.pending[:FRAME * 2]
            self.clock += FRAME
            probability = self.gate.probability(frame)
            if not self.frames:
                self.lead.append(frame)
                self.onset = self.onset + 1 if probability >= 0.62 else 0
                if self.onset < 3:
                    continue
                self.frames.extend(b"".join(self.lead))
                self.lead.clear()
                self.voiced = self.onset
                self.onset = 0
            else:
                self.frames.extend(frame)
                self.voiced += int(probability >= 0.62)
            self.quiet = 0 if probability >= 0.38 else self.quiet + 1
            if self.quiet >= 38:
                self.finish(final=True)
            elif len(self.frames) >= 24 * RATE * 2:
                self.finish(final=False)
            else:
                self.queue_preview()

    def publish(self, text, language, speaker):
        translation = self.languages.get(language)
        direction = {"en": "EN → RU", "ru": "RU → EN", "de": "DE → RU"}.get(language, language.upper())
        # Argos models translate a sentence at a time; a second sentence can be omitted
        # if it is appended to a long first sentence in the same translation request.
        for sentence in re.split(r'(?<=[.!?…])\s+(?=[A-ZА-ЯЁ«"])', normalize_terms(text)):
            translated = translation.translate(sentence) if translation else "Перевод доступен для русского, английского и немецкого."
            self.line(sentence, translated, speaker, direction)

    def finish(self, final):
        self.clear_preview(hide=False)
        pcm = bytes(self.frames)
        if final:
            self.frames.clear()
            self.quiet = 0
        if self.voiced < 6:
            self.voiced = 0
            if final:
                self.clear_preview()
            return
        samples = np.frombuffer(pcm, "<i2").astype(np.float32) / 32768
        language, confidence, _ = self.model.detect_language(audio=samples)
        fresh = self.clock - len(samples) - self.last_voice < 15 * RATE
        who = None
        if self.speaker_decoder is not None:
            self.speaker_decoder.AcceptWaveform(pcm)
            who = self.speakers.label(json.loads(self.speaker_decoder.FinalResult()))
            self.speaker_decoder.Reset()
        same_turn = fresh and language == self.previous_language and who == self.previous_speaker
        words = []
        if confidence >= (0.42 if language in self.languages else 0.75):
            segments, _ = self.model.transcribe(
                np.pad(samples, (0, 12800)) if final else samples,
                language=language, beam_size=3, temperature=0, word_timestamps=True,
                condition_on_previous_text=True, initial_prompt=self.previous_text if same_turn else None,
                repetition_penalty=1.08, no_repeat_ngram_size=5, hotwords=TECHNICAL_TERMS)
            for seg in segments:
                if reliable(seg):
                    words.extend(seg.words or [])
        if not final:
            # Prefer punctuation away from the uncertain right edge. Otherwise keep the
            # unfinished sentence as text and re-decode its audio tail with the next window.
            stable = [i for i, w in enumerate(words) if 1 <= w.end <= 21]
            ends = [i for i in stable if END_OF_SENTENCE.search(words[i].word.strip())]
            cut = ends[-1] if ends else (stable[-1] if stable else None)
            boundary = words[cut].end if cut is not None else 18.0
            if cut is not None and cut + 1 < len(words):
                boundary = (boundary + max(boundary, words[cut + 1].start)) / 2
            del self.frames[:int(min(boundary, 22) * RATE) * 2]
            words = words[:cut + 1] if cut is not None else []
        self.voiced = 0 if final else min(6, len(self.frames) // (FRAME * 2))
        text = "".join(w.word for w in words).strip()
        if final and words:
            # Whisper can emit an end token before the last spoken words of a clip.
            tail = samples[round(words[-1].end * RATE):]
            if len(tail) >= RATE * 0.6 and get_speech_timestamps(tail, threshold=0.6, min_speech_duration_ms=160):
                rest, _ = self.model.transcribe(np.pad(tail, (0, 12800)), language=language, beam_size=3,
                                                temperature=0, condition_on_previous_text=False,
                                                no_repeat_ngram_size=5)
                suffix = " ".join(seg.text.strip() for seg in rest if reliable(seg))
                text = (text + " " + suffix).strip()
        if not text:
            if final:
                self.flush_text()
                self.clear_preview()
            return
        if not same_turn:
            self.flush_text()
            self.previous_text = ""
        self.previous_language, self.previous_speaker = language, who
        self.previous_text = " ".join((self.previous_text + " " + text).split()[-40:])
        self.last_voice = self.clock
        combined = (self.unfinished + " " + text).strip()
        if final or END_OF_SENTENCE.search(text) or len(combined) >= 1000:
            self.unfinished = ""
            self.publish(combined, language, who)
            self.partial("")
            self.clear_preview()
        else:
            self.unfinished = combined
            self.partial(combined)

    def flush_text(self):
        if self.unfinished:
            self.publish(self.unfinished, self.previous_language, self.previous_speaker)
            self.unfinished = ""
            self.partial("")

    def flush(self):
        if self.frames:
            self.frames.extend(self.pending)
            self.finish(final=True)
        self.flush_text()
        self.pending.clear()
        self.lead.clear()
        self.onset = self.quiet = self.voiced = 0
        self.gate.reset()
