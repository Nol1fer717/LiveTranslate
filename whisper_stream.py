from collections import deque
import json
import os
import re
import queue
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import ctranslate2
import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.vad import get_speech_timestamps, get_vad_model
from vosk import KaldiRecognizer
from gpu_detection import nvidia_memory, supports_turbo


RATE = 16000
FRAME = 512  # Silero's 32 ms analysis window
END_OF_SENTENCE = re.compile(r"""[.!?…]["'»”)]*$""")
REPEATED_NUMBER = re.compile(r"(?<!\d)(\d+)(?:[\s.,;:\-–—]+\1(?!\d)){6,}")
PHANTOM_OUTRO = re.compile(r'(?i)(?:^|(?<=[.!?…])\s+)(?:продолжение следует|to be continued)\s*[.!?…]*\s*$')
SUBTITLE_CREDIT = re.compile(r'(?i)(?:^|(?<=[.!?…])\s+)(?:субтитры\s+(?:сделал[аи]?|подготовил[аи]?|перевёл|перевел[аи]?|создал[аи]?)\s+\S+(?:\s+\S+)?|subtitles\s+(?:made\s+by|by)\s+\S+(?:\s+\S+)?)\s*[.!?…]*\s*$')
TERM_PATTERNS = [
    (re.compile(r"(?<!\w)(?:ссш|ссн|эс[ -]?эс[ -]?(?:эйч|аш)|ssh)(?!\w)", re.I), "SSH"),
    (re.compile(r"(?<!\w)(?:постгрес(?:с(?:а|у|ом|е)?)?|позгрес(?:с(?:а|у|ом|е)?)?|postgress|postgresql)(?!\w)", re.I), "PostgreSQL"),
    (re.compile(r"(?<!\w)(?:энджинкс(?:а|у|ом|е)?|инжинкс(?:а|у|ом|е)?|nginx)(?!\w)", re.I), "Nginx"),
]
SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?…])\s+(?=[A-ZА-ЯЁ«"])')
_DLL_DIRECTORIES = []


def normalize_terms(text):
    text = re.sub(r"(?i)(\b(?:доступ|подключени\w*)\s+по\s+)(?:ссс|сс|cc|ccc)(?!\w)", r"\1SSH", text)
    for pattern, canonical in TERM_PATTERNS:
        text = pattern.sub(canonical, text)
    return text


def remove_phantom_outro(text):
    """Suppress Whisper's recurring standalone end-card hallucination."""
    return PHANTOM_OUTRO.sub('', SUBTITLE_CREDIT.sub('', text)).strip()


def merge_uncertain_turns(groups):
    """Keep brief uncertain words with adjacent speech without inventing a speaker."""
    result = [(label, list(parts)) for label, parts in groups]
    i = 0
    while i < len(result):
        label, parts = result[i]
        if label == 'Голос не определён' and len(''.join(parts).split()) <= 2 and len(result) > 1:
            if i > 0 and i + 1 < len(result) and result[i-1][0] == result[i+1][0]:
                result[i-1:i+2] = [('Голос не определён', result[i-1][1] + parts + result[i+1][1])]
                continue
            if i > 0:
                result[i-1:i+1] = [('Голос не определён', result[i-1][1] + parts)]
                continue
            result[:2] = [('Голос не определён', parts + result[1][1])]
            i = 1
            continue
        i += 1
    return result


def load_whisper(folder, turbo_folder=None):
    package_root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(sys.prefix) / "Lib" / "site-packages"
    for name in ("cublas", "cudnn", "cuda_nvrtc"):
        directory = package_root / "nvidia" / name / "bin"
        if directory.is_dir():
            _DLL_DIRECTORIES.append(os.add_dll_directory(str(directory)))
            if str(directory) not in os.environ.get("PATH", "").split(os.pathsep):
                os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
    try:
        cuda = ctranslate2.get_cuda_device_count() > 0
    except (RuntimeError, OSError):
        cuda = False
    candidates = []
    if cuda:
        if turbo_folder is not None and turbo_folder.is_dir() and supports_turbo(nvidia_memory()):
            candidates.append((turbo_folder, 'cuda', 'float16', 'Turbo'))
        candidates.append((folder, 'cuda', 'float16', 'Small'))
    candidates.append((folder, 'cpu', 'int8', 'Small'))
    last_error = None
    for model_folder, device, compute_type, name in candidates:
        model = None
        try:
            model = WhisperModel(str(model_folder), device=device, compute_type=compute_type, cpu_threads=3,
                                 num_workers=2, local_files_only=True)
            # Verify CUDA and model compatibility before opening the capture device.
            list(model.transcribe(np.zeros(RATE, dtype=np.float32), language='ru', beam_size=1)[0])
            model.livetranslate_model_name = name
            return model
        except (RuntimeError, OSError, ValueError) as exc:
            last_error = exc
            del model
    raise RuntimeError('Не удалось загрузить модель Whisper') from last_error


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


class StableWords:
    """Commit only words that agree in successive hypotheses."""
    def __init__(self):
        self.previous = []
        self.committed = []

    @staticmethod
    def key(word):
        return word.strip('.,!?…:;"\'«»()').casefold()

    def update(self, text):
        words = [w.strip('.,!?…:;"\'«»()') for w in text.split()]
        words = [w for w in words if w]
        keys = [self.key(w) for w in words]
        old = [self.key(w) for w in self.previous]
        committed = [self.key(w) for w in self.committed]
        if keys[:len(committed)] == committed:
            count = 0
            for a, b in zip(keys, old):
                if a != b: break
                count += 1
            if count > len(self.committed):
                self.committed.extend(words[len(self.committed):count])
        self.previous = words
        return ' '.join(self.committed)


class WhisperStream:
    """Buffer speech until a pause; retain undecided words across long windows."""
    def __init__(self, model, languages, speaker_model, speakers, line, partial, preview=None, diarizer=None, split_level=5):
        self.model = model
        self.languages = languages
        self.speakers = speakers
        self.diarizer = diarizer
        if not isinstance(split_level, int) or isinstance(split_level, bool) or not 1 <= split_level <= 10:
            raise ValueError('split_level must be between 1 and 10')
        # 1 = frequent boundaries; 10 = wait longer for a meaningful block.
        self.quiet_frames = round((0.48 + (split_level - 1) * 0.14) * RATE / FRAME)
        self.line = line
        self.partial = partial
        self.speaker_decoder = None
        if speaker_model is not None and diarizer is None:
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
        self.stable_words = StableWords()
        self.stable_language = None
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
                                                       condition_on_previous_text=False)
                text = " ".join(s.text.strip() for s in segments if reliable(s)).strip()
                if not text or info.language_probability < 0.42 or info.language not in self.languages:
                    continue
                text = remove_phantom_outro(normalize_terms(text))
                if not text:
                    continue
                with self.preview_lock:
                    if generation == self.preview_generation:
                        if self.stable_language is not None and info.language != self.stable_language:
                            continue
                        stable = self.stable_words.update(text)
                        display = (prefix + ' ' + stable).strip()
                        if display:
                            if stable and self.stable_language is None:
                                self.stable_language = info.language
                            self.preview((display, '', (self.stable_language or info.language).upper()))
            except Exception:
                # A preview is optional; the final recognition still reports its own errors.
                continue

    def queue_preview(self):
        if self.preview is None or len(self.frames) < 0.6 * RATE * 2 or self.clock - self.preview_at < 0.6 * RATE:
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
                committed = list(self.stable_words.committed)
                self.preview_generation += 1
                self.stable_words = StableWords()
                self.stable_language = None
                if hide:
                    self.preview(None)
                return committed
        return []

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
            if self.quiet >= self.quiet_frames:
                self.finish(final=True)
            elif len(self.frames) >= 24 * RATE * 2:
                self.finish(final=False)
            else:
                self.queue_preview()

    def publish(self, text, language, speaker):
        text = remove_phantom_outro(text)
        if not text:
            return
        translation = self.languages.get(language)
        direction = {"en": "EN → RU", "ru": "RU → EN", "de": "DE → RU"}.get(language, language.upper())
        # Argos models translate a sentence at a time; a second sentence can be omitted
        # if it is appended to a long first sentence in the same translation request.
        for sentence in SENTENCE_BOUNDARY.split(normalize_terms(text)):
            translated = (translation.translate(sentence) if translation else
                          "Немецкий перевод не установлен. Запустите установщик снова и выберите немецкий язык."
                          if language == "de" else "Перевод для этого языка не установлен.")
            self.line(sentence, translated, speaker, direction)

    def finish(self, final):
        committed = self.clear_preview(hide=False)
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
        # An unknown speaker is not an identity: two consecutive unknown voices
        # must not share a prompt or be combined into one person's sentence.
        identified = self.speaker_decoder is None or (who is not None and who != "Голос не определён")
        same_turn = self.diarizer is None and fresh and identified and language == self.previous_language and who == self.previous_speaker
        words = []
        if confidence >= (0.42 if language in self.languages else 0.75):
            segments, _ = self.model.transcribe(
                np.pad(samples, (0, 12800)) if final else samples,
                language=language, beam_size=3, temperature=0, word_timestamps=True,
                condition_on_previous_text=True, initial_prompt=self.previous_text if same_turn else None,
                repetition_penalty=1.08, no_repeat_ngram_size=5)
            for seg in segments:
                if reliable(seg):
                    words.extend(seg.words or [])
        # Preserve words already shown; subsequent decoding may revise them.
        for i, shown in enumerate(committed):
            if i >= len(words):
                last_end = words[-1].end if words else 0.0
                words.append(SimpleNamespace(word=(' ' if i else '') + shown, start=last_end, end=last_end))
            else:
                original = words[i]
                words[i] = SimpleNamespace(word=(' ' if i else '') + shown, start=original.start, end=original.end)
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
        if self.diarizer is not None and words:
            if final:
                tail_start = round(words[-1].end * RATE)
                tail = samples[tail_start:]
                if len(tail) >= RATE * 0.6 and get_speech_timestamps(tail, threshold=0.6, min_speech_duration_ms=160):
                    rest, _ = self.model.transcribe(np.pad(tail, (0, 12800)), language=language, beam_size=3,
                                                    temperature=0, word_timestamps=True,
                                                    condition_on_previous_text=False, no_repeat_ngram_size=5)
                    for seg in rest:
                        if reliable(seg):
                            for word in seg.words or []:
                                if word.start < len(tail) / RATE:
                                    words.append(SimpleNamespace(word=word.word, start=word.start + tail_start / RATE,
                                                                 end=word.end + tail_start / RATE))
            turns = self.diarizer.turns(samples)
            groups = []
            for word in words:
                midpoint = (word.start + word.end) / 2
                matches = {name for start, end, name in turns if start <= midpoint <= end}
                if not matches:
                    # Small segmentation gaps should not split a sentence into
                    # one-word translations. Overlapping speakers stay unknown.
                    nearby = [(min(abs(midpoint - start), abs(midpoint - end)), name)
                              for start, end, name in turns]
                    if nearby:
                        distance, name = min(nearby)
                        if distance <= 0.4:
                            matches = {name}
                label = next(iter(matches)) if len(matches) == 1 else 'Голос не определён'
                if not groups or groups[-1][0] != label:
                    groups.append((label, []))
                groups[-1][1].append(word.word)
            self.flush_text()
            for label, parts in merge_uncertain_turns(groups):
                text = ''.join(parts).strip()
                if text:
                    self.publish(text, language, label)
            self.previous_text = ''
            self.previous_language = self.previous_speaker = None
            self.last_voice = self.clock
            self.partial('')
            self.clear_preview()
            return
        text = "".join(w.word for w in words).strip()
        if final and words:
            # Whisper can emit an end token before the last spoken words of a clip.
            tail = samples[round(words[-1].end * RATE):]
            if len(tail) >= RATE * 0.6 and get_speech_timestamps(tail, threshold=0.6, min_speech_duration_ms=160):
                rest, _ = self.model.transcribe(np.pad(tail, (0, 12800)), language=language, beam_size=3,
                                                temperature=0, word_timestamps=True, condition_on_previous_text=False,
                                                no_repeat_ngram_size=5)
                # Padding helps Whisper decode the end, but is not actual speech.
                suffix = "".join(word.word for seg in rest if reliable(seg)
                                 for word in (seg.words or []) if word.start < len(tail) / RATE).strip()
                text = (text + " " + suffix).strip()
        text = remove_phantom_outro(text)
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
