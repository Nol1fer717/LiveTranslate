from __future__ import annotations

import audioop
import ctypes
import json
import queue
import re
import sys
import threading
import time
import wave
from contextlib import ExitStack
from pathlib import Path

import ctranslate2
import numpy as np
import pyaudiowpatch as pa
import sentencepiece
from sacremoses import MosesDetokenizer, MosesPunctNormalizer, MosesTokenizer
from subword_nmt.apply_bpe import BPE
from vosk import KaldiRecognizer, Model, SetLogLevel
from whisper_stream import StableWords, WhisperStream, UnrecognizedAudioError, StuckRecognizerError, remove_phantom_outro
from partial_translation import PartialTranslator
import diagnostics

ROOT = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
DATA = ROOT / "data"
SPEAKER_PATH = DATA / "vosk-model-spk-0.4"
MODELS = {"ru": "vosk-model-small-ru-0.22", "en": "vosk-model-small-en-us-0.15"}
SetLogLevel(-1)
DEVICE_LOCK = threading.Lock()
STOP_WAIT_SECONDS = 10.0


class SourceStop:
    """Per-source cancellation that also observes the session stop event."""
    def __init__(self, session_stop):
        self.session_stop = session_stop
        self.local_stop = threading.Event()

    def is_set(self):
        return self.session_stop.is_set() or self.local_stop.is_set()

    def set(self):
        self.local_stop.set()


def prepare_spoken_russian(text):
    """Clarify a few ambiguous colloquialisms for the local translation model.

    This only changes the model input; the original transcript stays intact.
    """
    text = re.sub(r'(?i)\bпоходу(?=\s+(?:как-то|это|он[аои]?|я|мы|вы|ты|они)\b)', 'похоже', text)
    text = re.sub(r'(?i)\bху[её]во\s+работает\b', 'пиздец как плохо работает', text)
    text = re.sub(r'(?i)\bработает\s+ху[её]во\b', 'работает пиздец как плохо', text)
    return text


def devices():
    with pa.PyAudio() as audio:
        api = audio.get_host_api_info_by_type(pa.paWASAPI)
        inputs = [d for d in audio.get_device_info_generator()
                  if d["hostApi"] == api["index"] and d["maxInputChannels"]]
        mics = [d for d in inputs if not d["isLoopbackDevice"]]
        loops = [d for d in inputs if d["isLoopbackDevice"]]
        mics.sort(key=lambda d: d["index"] != api["defaultInputDevice"])
        if api["defaultOutputDevice"] >= 0:
            name = audio.get_device_info_by_index(api["defaultOutputDevice"])["name"]
            loops.sort(key=lambda d: not d["name"].startswith(name))
        return mics, loops


class Language:
    def __init__(self, src, load_speech=True):
        self.source = src
        dst = "ru" if src == "en" else "en"
        folder = DATA / f"translate-{src}_{dst}-1_9"
        self.speech = Model(str(DATA / MODELS[src])) if load_speech and src in MODELS else None
        self.tokens = sentencepiece.SentencePieceProcessor(model_proto=(folder / "sentencepiece.model").read_bytes())
        self.translator = ctranslate2.Translator(str(folder / "model"), device="cpu",
                                                  compute_type="auto", intra_threads=2)

    def translate(self, text):
        if self.source == "ru":
            text = prepare_spoken_russian(text)
        pieces = self.tokens.encode(text, out_type=str)
        result = self.translator.translate_batch([pieces], beam_size=3)[0]
        return self.tokens.decode(result.hypotheses[0]).strip()


class EnglishToGerman:
    def __init__(self, russian):
        folder = DATA / "translate-en_de-1_3"
        self.tokens = sentencepiece.SentencePieceProcessor(model_proto=(folder / "sentencepiece.model").read_bytes())
        self.translator = ctranslate2.Translator(str(folder / "model"), device="cpu", compute_type="auto", intra_threads=2)
        self.russian = russian

    def translate(self, text):
        english = self.russian.translate(text)
        pieces = self.tokens.encode(english, out_type=str)
        result = self.translator.translate_batch([pieces], beam_size=3)[0]
        return self.tokens.decode(result.hypotheses[0]).strip()


class GermanTranslation:
    def __init__(self, english):
        folder = DATA / "translate-de_en-1_9"
        with (folder / "bpe.model").open(encoding="utf-8") as source:
            self.bpe = BPE(source)
        self.normalizer = MosesPunctNormalizer("de")
        self.tokenizer = MosesTokenizer("de")
        self.detokenizer = MosesDetokenizer("en")
        self.translator = ctranslate2.Translator(str(folder / "model"), device="cpu",
                                                  compute_type="auto", intra_threads=2)
        self.english = english

    def translate(self, text):
        words = self.tokenizer.tokenize(self.normalizer.normalize(text))
        pieces = self.bpe.segment_tokens(words)
        result = self.translator.translate_batch([pieces], beam_size=3)[0]
        english = self.detokenizer.detokenize(" ".join(result.hypotheses[0]).replace("@@ ", "").split())
        return self.english.translate(english)


def mono16(data, channels, loopback=False):
    if channels == 1:
        return data
    frames = np.frombuffer(data, dtype="<i2").reshape(-1, channels)
    if channels > 2:
        levels = np.sqrt(np.mean(frames.astype(np.float32) ** 2, axis=0))
        active = levels > max(1.0, float(levels.max()) * 0.01)
        if active.any():
            frames = frames[:, active]
    return frames.mean(axis=1).astype("<i2").tobytes()


class SessionSpeakers:
    """Cluster phrase embeddings within a single system-audio session."""
    def __init__(self):
        self.centres = []

    def label(self, result):
        unknown = "Голос не определён"
        frames = result.get("spk_frames", 0)
        if frames < 65 or not result.get("spk"):
            return unknown
        vector = np.asarray(result["spk"], dtype=float)
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm == 0:
            return unknown
        vector /= norm
        scores = [float(centre @ vector) for centre in self.centres]
        if scores:
            index = int(np.argmax(scores))
            best = scores[index]
            if best >= (0.68 if frames < 150 else 0.59):
                if len(scores) > 1 and best - sorted(scores)[-2] < 0.08:
                    return unknown
                if frames >= 150:
                    centre = self.centres[index] * 0.8 + vector * 0.2
                    self.centres[index] = centre / np.linalg.norm(centre)
                return f"Голос {index + 1}"
            if best > 0.45:
                return unknown
        if frames < 150:
            return unknown
        self.centres.append(vector)
        return f"Голос {len(self.centres)}"


def capture(audio, device, language, target, stop, emit, record_path, speaker_model=None, whisper=None, diarizer=None, split_level=5, quiet_mode=False):
    """Capture continuously while speech recognition and translation consume queued blocks."""
    original_emit = emit
    emissions_closed = threading.Event()
    def emit(*args):
        if not emissions_closed.is_set():
            original_emit(*args)
    chunks = queue.Queue(maxsize=200)
    analysis = queue.Queue(maxsize=6000)  # Up to ten minutes of compact mono PCM if inference falls behind.
    errors = []
    late_pcm = []
    gap = object()
    end = object()
    rate = int(device["defaultSampleRate"])
    channels = int(device["maxInputChannels"])
    speakers = SessionSpeakers() if speaker_model is not None else None
    automatic = None
    partial_translator = None
    if whisper is None:
        decoder = KaldiRecognizer(language.speech, 16000)
        if speakers is not None:
            decoder.SetSpkModel(speaker_model)
        partial_translator = PartialTranslator({language.source: language}, lambda value: emit('preview', target, value))
    else:
        automatic = WhisperStream(whisper, language, speaker_model, speakers,
                                  lambda *line: emit("line", target, line),
                                  lambda text: emit("partial", target, text),
                                  lambda result: emit("preview", target, result), diarizer=diarizer, split_level=split_level, quiet_mode=quiet_mode)
    resampler = None
    partial = ""
    stable_partial = StableWords()

    def callback(data, count, timing, flags):
        try:
            chunks.put_nowait((data, time.monotonic(), flags))
        except queue.Full:
            stop.set()
            errors.append(RuntimeError("Не удалось вовремя считать звук с устройства."))
        return None, pa.paContinue

    def publish(result):
        nonlocal partial, stable_partial
        if partial_translator is not None:
            partial_translator.reset()
        phrase = json.loads(result)
        text = phrase.get("text", "").strip()
        if stable_partial.committed:
            words = text.split()
            text = ' '.join(stable_partial.committed + words[len(stable_partial.committed):])
        text = remove_phantom_outro(text)
        if text:
            who = speakers.label(phrase) if speakers is not None else None
            try:
                translated = language.translate(text)
            except Exception as exc:
                diagnostics.log_error('translate', type(exc), exc.__traceback__)
                translated = 'Не удалось перевести фразу. Исходный текст сохранён.'
            emit("line", target, (text, translated, who))
        emit("preview", target, None)
        partial = ""
        stable_partial = StableWords()
        emit("partial", target, "")

    def flush():
        if automatic is not None:
            automatic.flush()
        else:
            publish(decoder.FinalResult())
            decoder.Reset()

    def recognize():
        nonlocal partial
        try:
            for item in iter(analysis.get, end):
                if item is gap:
                    flush()
                elif automatic is not None:
                    automatic.accept(item)
                elif decoder.AcceptWaveform(item):
                    publish(decoder.Result())
                else:
                    current = json.loads(decoder.PartialResult()).get("partial", "")
                    stable = stable_partial.update(remove_phantom_outro(current))
                    if stable and stable != partial:
                        partial = stable
                        emit("partial", target, stable)
                        emit('preview', target, (stable, '', language.source.upper()))
                        partial_translator.submit(stable, language.source)
            flush()
        except Exception as exc:
            errors.append(exc)
            stop.set()
        finally:
            if automatic is not None:
                if automatic.close() is False:
                    errors.append(StuckRecognizerError('Распознавание не завершилось. Перезапустите приложение.'))
                    stop.set()
            if partial_translator is not None:
                if partial_translator.close() is False:
                    errors.append(StuckRecognizerError('Перевод не завершился. Перезапустите приложение.'))
                    stop.set()

    def submit(item):
        try:
            analysis.put_nowait(item)
        except queue.Full:
            raise RuntimeError("Распознавание отстало более чем на десять минут.")

    worker = None
    def close_if_safe(resource):
        if worker is None or not worker.is_alive():
            resource.close()

    with ExitStack() as stack:
        if automatic is not None:
            stack.callback(close_if_safe, automatic)
        if partial_translator is not None:
            stack.callback(close_if_safe, partial_translator)
        # PortAudio initializes COM on its owner thread. Each WASAPI worker also needs it.
        result = ctypes.windll.ole32.CoInitializeEx(None, 0)
        if result < 0:
            raise OSError(f"Не удалось инициализировать COM: {result:#x}")
        stack.callback(ctypes.windll.ole32.CoUninitialize)
        with DEVICE_LOCK:
            active = audio.get_device_info_by_index(device["index"])
            if active["name"] != device["name"]:
                raise RuntimeError("Список устройств изменился. Обновите его.")
            stream = audio.open(input=True, input_device_index=device["index"], format=pa.paInt16,
                                channels=channels, rate=rate, frames_per_buffer=rate // 10,
                                stream_callback=callback, start=False)
        def close_stream():
            with DEVICE_LOCK:
                stream.close()
        stack.callback(close_stream)
        writer = None
        if record_path:
            writer = stack.enter_context(wave.open(str(record_path), "wb"))
            writer.setparams((1, 2, 16000, 0, "NONE", ""))
        with DEVICE_LOCK:
            started = time.monotonic()
            stream.start_stream()
        worker = threading.Thread(target=recognize, daemon=True)
        worker.start()
        emit("ready", target, None)
        last_packet = started
        in_gap = False
        captured_until = None

        def pad_recording(until):
            if writer is None:
                return
            missing = round((until - started) * 16000) - writer.tell()
            while missing > 0:
                count = min(16000, missing)
                writer.writeframesraw(bytes(2 * count))
                missing -= count

        try:
            while True:
                if stop.is_set() and captured_until is None:
                    captured_until = time.monotonic()
                    if stream.is_active():
                        stream.stop_stream()
                try:
                    data, arrival, flags = chunks.get(timeout=0.1)
                except queue.Empty:
                    if stop.is_set():
                        if captured_until is not None:
                            break
                        continue
                    if not stream.is_active():
                        raise RuntimeError("Аудиоустройство отключено.")
                    if not in_gap and time.monotonic() - last_packet >= 1.3:
                        submit(gap)
                        in_gap = True
                    continue
                packet_start = arrival - len(data) / (2 * channels * rate)
                missing = packet_start - last_packet
                if missing > 0.18 or flags & pa.paInputOverflow:
                    pad_recording(packet_start)
                    resampler = None
                    if missing >= 1.3 and not in_gap:
                        submit(gap)
                pcm, resampler = audioop.ratecv(mono16(data, channels, device.get("isLoopbackDevice", False)), 2, 1, rate, 16000, resampler)
                if writer:
                    writer.writeframesraw(pcm)
                last_packet = arrival
                in_gap = False
                if not errors:
                    submit(pcm)
                elif isinstance(errors[0], UnrecognizedAudioError):
                    late_pcm.append(pcm)
        finally:
            try:
                if stream.is_active():
                    stream.stop_stream()
                pad_recording(captured_until if captured_until is not None else time.monotonic())
                if writer:
                    writer.close()
            finally:
                deadline = time.monotonic() + STOP_WAIT_SECONDS
                while worker.is_alive() and time.monotonic() < deadline:
                    try:
                        analysis.put(end, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                worker.join(timeout=max(0, deadline - time.monotonic()))
                if worker.is_alive():
                    emissions_closed.set()
                    errors.append(StuckRecognizerError('Распознавание не завершилось. Перезапустите приложение.'))
        if errors:
            if any(isinstance(error, StuckRecognizerError) for error in errors):
                errors[0].restart_required = True
            if isinstance(errors[0], UnrecognizedAudioError):
                queued = []
                while not analysis.empty():
                    item = analysis.get_nowait()
                    if isinstance(item, bytes):
                        queued.append(item)
                errors[0].pcm += b''.join(queued + late_pcm)
            raise errors[0]
