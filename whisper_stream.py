from collections import deque
import json
import os
import re
import queue
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import ctranslate2
import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.vad import get_speech_timestamps, get_vad_model
from vosk import KaldiRecognizer
from gpu_detection import nvidia_memory, supports_turbo
from partial_translation import PartialTranslator
import diagnostics


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


class UnrecognizedAudioError(RuntimeError):
    """Keep the undecoded audio in memory for optional user-directed recovery."""
    def __init__(self, pcm):
        super().__init__('Не удалось распознать длительный фрагмент речи. Его можно сохранить вручную.')
        self.pcm = pcm


class StuckRecognizerError(RuntimeError):
    pass


def normalize_terms(text):
    text = re.sub(r"(?i)(\b(?:доступ|подключени\w*)\s+по\s+)(?:ссс|сс|cc|ccc)(?!\w)", r"\1SSH", text)
    for pattern, canonical in TERM_PATTERNS:
        text = pattern.sub(canonical, text)
    return text


def remove_phantom_outro(text):
    """Suppress Whisper's recurring standalone end-card hallucination."""
    return PHANTOM_OUTRO.sub('', SUBTITLE_CREDIT.sub('', text)).strip()


def remove_preview_overlap(words, synthetic):
    """Discard only a tail prefix already committed without audio timestamps."""
    count = 0
    while count < min(len(words), len(synthetic)) and StableWords.key(words[count].word.strip()) == StableWords.key(synthetic[count].strip()):
        count += 1
    return words[count:]


def remove_tail_boundary_overlap(previous, tail):
    """Drop matching words re-decoded at the cut, keeping later repetitions."""
    if not previous or not tail or tail[0].start > 0.25:
        return tail
    old = [StableWords.key(word.word) for word in previous]
    new = [StableWords.key(word.word) for word in tail]
    for count in range(min(len(old), len(new)), 0, -1):
        if old[-count:] == new[:count] and all(new[:count]):
            return tail[count:]
    return tail


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


def amplify_quiet_audio(samples):
    """Limited gain for an explicitly selected quiet-voice profile."""
    rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64))) if samples.size else 0.0
    if rms < 0.0003:
        return samples
    return np.clip(samples * max(1.0, min(6.0, 0.035 / rms)), -1.0, 1.0).astype(np.float32)


class SpeechGate:
    """Keep Silero's recurrent state private to each audio device."""
    def __init__(self, quiet_mode=False):
        self.session = get_vad_model().session
        self.quiet_mode = quiet_mode
        self.reset()

    def reset(self):
        self.h = np.zeros((1, 1, 128), np.float32)
        self.c = np.zeros_like(self.h)
        self.context = np.zeros(64, np.float32)
        self.weak_h = np.zeros_like(self.h)
        self.weak_c = np.zeros_like(self.c)
        self.weak_context = np.zeros_like(self.context)
        self.adaptive_detected = False

    def probability(self, frame):
        samples = np.frombuffer(frame, "<i2").astype(np.float32) / 32768
        if self.quiet_mode:
            samples = amplify_quiet_audio(samples)
        inputs = np.concatenate((self.context, samples))[None, :]
        self.context = samples[-64:]
        probability, self.h, self.c = self.session.run(None, {"input": inputs, "h": self.h, "c": self.c})
        result = float(probability.item()) if np.max(np.abs(samples)) > 0.0003 else 0.0
        rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
        if not self.quiet_mode and .0003 <= rms < .006:
            boosted = amplify_quiet_audio(samples)
            candidate, self.weak_h, self.weak_c = self.session.run(
                None, {'input': np.concatenate((self.weak_context, boosted))[None, :],
                       'h': self.weak_h, 'c': self.weak_c})
            self.weak_context = boosted[-64:]
            weak_probability = float(candidate.item())
            if weak_probability >= .82:
                result = max(result, weak_probability)
                self.adaptive_detected = True
        else:
            self.weak_h.fill(0); self.weak_c.fill(0); self.weak_context.fill(0)
        return result


class StableWords:
    """Commit only words that agree in successive hypotheses."""
    def __init__(self):
        self.previous = []
        self.committed = []

    @staticmethod
    def key(word):
        return word.strip().strip('.,!?…:;"\'«»()').casefold()

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
    def __init__(self, model, languages, speaker_model, speakers, line, partial, preview=None, diarizer=None, split_level=5, quiet_mode=False):
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
        self.quiet_mode = quiet_mode
        self.gate = SpeechGate(quiet_mode=quiet_mode)
        self.vad_frames = self.vad_below = 0
        self.vad_peak = 0.0
        self.pending = bytearray()
        self.lead = deque(maxlen=9)
        self.frames = bytearray()
        self.onset = self.quiet = self.voiced = 0
        self.previous_text = ""
        self.previous_language = self.previous_speaker = None
        self.unfinished = ""
        self.pending_preview_overlap = []
        self.last_voice = self.clock = 0
        self.next_window_bytes = 24 * RATE * 2
        self.preview = preview
        self.preview_lock = threading.Lock()
        self.preview_generation = 0
        self.stable_words = StableWords()
        self.stable_language = None
        self.last_preview_text = None
        self.preview_at = 0
        self.preview_queue = queue.Queue(maxsize=1)
        self.preview_thread = None
        self.closed = False
        self.close_ok = True
        self.partial_translator = PartialTranslator(languages, preview) if preview is not None else None
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
                if self.quiet_mode or self.gate.adaptive_detected:
                    audio = amplify_quiet_audio(audio)
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
                        visible = stable.split()
                        overlap = self.pending_preview_overlap
                        matched = 0
                        while matched < min(len(visible), len(overlap)) and StableWords.key(visible[matched]) == StableWords.key(overlap[matched]):
                            matched += 1
                        display = (prefix + ' ' + ' '.join(visible[matched:])).strip()
                        if display and display != self.last_preview_text:
                            if stable and self.stable_language is None:
                                self.stable_language = info.language
                            self.last_preview_text = display
                            self.preview((display, '', (self.stable_language or info.language).upper()))
                            self.partial_translator.submit(display, self.stable_language or info.language)
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
                if self.partial_translator is not None:
                    self.partial_translator.reset()
                committed = list(self.stable_words.committed)
                self.preview_generation += 1
                self.stable_words = StableWords()
                self.stable_language = None
                self.last_preview_text = None
                if hide:
                    self.preview(None)
                return committed
        return []

    def close(self):
        if self.closed:
            return self.close_ok
        self.closed = True
        if self.preview_thread is not None:
            self.clear_preview()
            try:
                self.preview_queue.get_nowait()
            except queue.Empty:
                pass
            self.preview_queue.put(None)
            self.preview_thread.join(timeout=2)
        translation_closed = True
        if self.partial_translator is not None:
            translation_closed = self.partial_translator.close()
        self.close_ok = (self.preview_thread is None or not self.preview_thread.is_alive()) and translation_closed
        return self.close_ok

    def accept(self, pcm):
        self.pending.extend(pcm)
        # Silero often assigns whispers a much lower probability than voiced
        # speech. Keep the normal profile strict; only the explicit quiet
        # profile uses the sensitive thresholds.
        onset_threshold = 0.08 if self.quiet_mode else 0.62
        continuation_threshold = 0.05 if self.quiet_mode else 0.38
        while len(self.pending) >= FRAME * 2:
            frame = bytes(self.pending[:FRAME * 2])
            del self.pending[:FRAME * 2]
            self.clock += FRAME
            probability = self.gate.probability(frame)
            self.vad_frames += 1
            self.vad_peak = max(self.vad_peak, probability)
            self.vad_below += int(probability < onset_threshold)
            if self.vad_frames >= 313:  # Approximately ten seconds, not every 32 ms.
                diagnostics.record_vad_summary(self.vad_frames, self.vad_peak, self.vad_below)
                self.vad_frames = self.vad_below = 0
                self.vad_peak = 0.0
            if not self.frames:
                self.lead.append(frame)
                self.onset = self.onset + 1 if probability >= onset_threshold else 0
                if self.onset < 3:
                    continue
                self.frames.extend(b"".join(self.lead))
                self.lead.clear()
                self.voiced = self.onset
                self.onset = 0
            else:
                self.frames.extend(frame)
                self.voiced += int(probability >= onset_threshold)
            self.quiet = 0 if probability >= continuation_threshold else self.quiet + 1
            if self.quiet >= self.quiet_frames:
                self.finish(final=True)
            elif len(self.frames) >= self.next_window_bytes:
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
            try:
                started = time.monotonic()
                translated = (translation.translate(sentence) if translation else
                              "Немецкий перевод не установлен. Запустите установщик снова и выберите немецкий язык."
                              if language == "de" else "Перевод для этого языка не установлен.")
                diagnostics.record_timing('final_translation', time.monotonic() - started)
            except Exception as exc:
                diagnostics.log_error('translate', type(exc), exc.__traceback__)
                translated = 'Не удалось перевести фразу. Исходный текст сохранён.'
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
        quiet_final = final and self.quiet_mode
        if quiet_final:
            # Whispered previews are especially unstable; don't force
            # their unsupported words into the independently decoded result.
            committed = []
        adaptive_detected = self.gate.adaptive_detected
        if final:
            self.gate.adaptive_detected = False
        if self.quiet_mode or adaptive_detected:
            samples = amplify_quiet_audio(samples)
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
        if confidence >= (0.42 if language in self.languages or language == 'de' else 0.75):
            segments, _ = self.model.transcribe(
                np.pad(samples, (0, 12800)) if final else samples,
                language=language, beam_size=3, temperature=0, word_timestamps=True,
                condition_on_previous_text=True, initial_prompt=self.previous_text if same_turn and not quiet_final else None,
                repetition_penalty=1.08, no_repeat_ngram_size=5)
            for seg in segments:
                if reliable(seg):
                    words.extend(seg.words or [])
        if self.pending_preview_overlap and words:
            retained = remove_preview_overlap(words, self.pending_preview_overlap)
            matched = len(words) - len(retained)
            words = retained
            if matched and [StableWords.key(x) for x in committed[:matched]] == [StableWords.key(x) for x in self.pending_preview_overlap[:matched]]:
                committed = committed[matched:]
            self.pending_preview_overlap = []
        real_word_count = len(words)
        synthetic = committed[len(words):]
        # Preserve words already shown; subsequent decoding may revise them.
        for i, shown in enumerate(committed):
            if i >= len(words):
                last_end = words[-1].end if words else 0.0
                words.append(SimpleNamespace(word=(' ' if i else '') + shown, start=last_end, end=last_end))
            else:
                original = words[i]
                punctuation = re.search(r'[.!?…]+["\'»”)]*$', original.word.strip())
                suffix = punctuation.group(0) if punctuation else ''
                words[i] = SimpleNamespace(word=(' ' if i else '') + shown + suffix, start=original.start, end=original.end)
        if not final:
            # Prefer punctuation away from the uncertain right edge. Otherwise keep the
            # unfinished sentence as text and re-decode its audio tail with the next window.
            stable = [i for i, w in enumerate(words[:real_word_count]) if 1 <= w.end <= 21]
            ends = [i for i in stable if END_OF_SENTENCE.search(words[i].word.strip())]
            cut = ends[-1] if ends else (stable[-1] if stable else None)
            if cut is None:
                if self.preview is not None:
                    with self.preview_lock:
                        self.stable_words.committed = committed
                if len(self.frames) >= 30 * RATE * 2:
                    raise UnrecognizedAudioError(bytes(self.frames) + bytes(self.pending))
                self.next_window_bytes = len(self.frames) + 2 * RATE * 2
                return
            boundary = words[cut].end
            if cut is not None and cut + 1 < len(words):
                boundary = (boundary + max(boundary, words[cut + 1].start)) / 2
            del self.frames[:int(min(boundary, 22) * RATE) * 2]
            if synthetic and cut == real_word_count - 1:
                words = words[:cut + 1] + words[real_word_count:]
                self.pending_preview_overlap = list(synthetic)
            else:
                words = words[:cut + 1]
        self.next_window_bytes = 24 * RATE * 2
        self.voiced = 0 if final else min(6, len(self.frames) // (FRAME * 2))
        # A whispered utterance can leave residual breath in the tail.
        # Re-decoding it as an independent clip often hallucinates extra words.
        skip_quiet_tail = self.quiet_mode
        if self.diarizer is not None and words:
            if final and not skip_quiet_tail:
                tail_start = round(words[-1].end * RATE)
                tail = samples[tail_start:]
                if len(tail) >= RATE * 0.6 and get_speech_timestamps(tail, threshold=0.6, min_speech_duration_ms=160):
                    rest, _ = self.model.transcribe(np.pad(tail, (0, 12800)), language=language, beam_size=3,
                                                    temperature=0, word_timestamps=True,
                                                    condition_on_previous_text=False, no_repeat_ngram_size=5)
                    tail_words = [word for seg in rest if reliable(seg) for word in (seg.words or [])
                                  if word.start < len(tail) / RATE]
                    for word in remove_tail_boundary_overlap(words, remove_preview_overlap(tail_words, synthetic)):
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
            for label, parts in groups:
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
        if final and words and not skip_quiet_tail:
            # Whisper can emit an end token before the last spoken words of a clip.
            tail = samples[round(words[-1].end * RATE):]
            if len(tail) >= RATE * 0.6 and get_speech_timestamps(tail, threshold=0.6, min_speech_duration_ms=160):
                rest, _ = self.model.transcribe(np.pad(tail, (0, 12800)), language=language, beam_size=3,
                                                temperature=0, word_timestamps=True, condition_on_previous_text=False,
                                                no_repeat_ngram_size=5)
                # Padding helps Whisper decode the end, but is not actual speech.
                tail_words = [word for seg in rest if reliable(seg) for word in (seg.words or [])
                              if word.start < len(tail) / RATE]
                tail_words = remove_tail_boundary_overlap(words, remove_preview_overlap(tail_words, synthetic))
                suffix = "".join(word.word for word in tail_words).strip()
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
