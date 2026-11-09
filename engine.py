from __future__ import annotations

import audioop
import ctypes
import json
import queue
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
from whisper_stream import WhisperStream

ROOT = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
DATA = ROOT / "data"
SPEAKER_PATH = DATA / "vosk-model-spk-0.4"
MODELS = {"ru": "vosk-model-small-ru-0.22", "en": "vosk-model-small-en-us-0.15"}
SetLogLevel(-1)
DEVICE_LOCK = threading.Lock()


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
    def __init__(self, src):
        self.source = src
        dst = "ru" if src == "en" else "en"
        folder = DATA / f"translate-{src}_{dst}-1_9"
        self.speech = Model(str(DATA / MODELS[src])) if src in MODELS else None
        self.tokens = sentencepiece.SentencePieceProcessor(model_proto=(folder / "sentencepiece.model").read_bytes())
        self.translator = ctranslate2.Translator(str(folder / "model"), device="cpu",
                                                  compute_type="auto", intra_threads=2)

    def translate(self, text):
        pieces = self.tokens.encode(text, out_type=str)
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
    if loopback and channels > 2:
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


def capture(audio, device, language, target, stop, emit, record_path, speaker_model=None, whisper=None):
    """Capture continuously while speech recognition and translation consume queued blocks."""
    chunks = queue.Queue(maxsize=200)
    analysis = queue.Queue(maxsize=6000)  # Up to ten minutes of compact mono PCM if inference falls behind.
    errors = []
    gap = object()
    end = object()
    rate = int(device["defaultSampleRate"])
    channels = int(device["maxInputChannels"])
    speakers = SessionSpeakers() if speaker_model is not None else None
    automatic = None
    if whisper is None:
        decoder = KaldiRecognizer(language.speech, 16000)
        if speakers is not None:
            decoder.SetSpkModel(speaker_model)
    else:
        automatic = WhisperStream(whisper, language, speaker_model, speakers,
                                  lambda *line: emit("line", target, line),
                                  lambda text: emit("partial", target, text),
                                  lambda result: emit("preview", target, result))
    resampler = None
    partial = ""
    last_partial_translation = 0.0

    def callback(data, count, timing, flags):
        try:
            chunks.put_nowait((data, time.monotonic(), flags))
        except queue.Full:
            stop.set()
            errors.append(RuntimeError("Не удалось вовремя считать звук с устройства."))
        return None, pa.paContinue

    def publish(result):
        nonlocal partial
        phrase = json.loads(result)
        text = phrase.get("text", "").strip()
        if text:
            who = speakers.label(phrase) if speakers is not None else None
            emit("line", target, (text, language.translate(text), who))
        emit("preview", target, None)
        partial = ""
        emit("partial", target, "")

    def flush():
        if automatic is not None:
            automatic.flush()
        else:
            publish(decoder.FinalResult())
            decoder.Reset()

    def recognize():
        nonlocal partial, last_partial_translation
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
                    if current != partial:
                        partial = current
                        emit("partial", target, partial)
                        if not current:
                            emit("preview", target, None)
                        elif time.monotonic() - last_partial_translation >= 1.0:
                            last_partial_translation = time.monotonic()
                            emit("preview", target, (current, language.translate(current), language.source.upper()))
            flush()
        except Exception as exc:
            errors.append(exc)
            stop.set()
        finally:
            if automatic is not None:
                automatic.close()

    def submit(item):
        try:
            analysis.put_nowait(item)
        except queue.Full:
            raise RuntimeError("Распознавание отстало более чем на десять минут.")

    with ExitStack() as stack:
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
        worker = threading.Thread(target=recognize)
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
        finally:
            try:
                if stream.is_active():
                    stream.stop_stream()
                pad_recording(captured_until if captured_until is not None else time.monotonic())
                if writer:
                    writer.close()
            finally:
                while worker.is_alive():
                    try:
                        analysis.put(end, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                worker.join()
        if errors:
            raise errors[0]
