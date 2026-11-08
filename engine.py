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
from vosk import KaldiRecognizer, Model, SetLogLevel

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
        dst = "ru" if src == "en" else "en"
        folder = DATA / f"translate-{src}_{dst}-1_9"
        self.speech = Model(str(DATA / MODELS[src]))
        self.tokens = sentencepiece.SentencePieceProcessor(model_proto=(folder / "sentencepiece.model").read_bytes())
        self.translator = ctranslate2.Translator(str(folder / "model"), device="cpu",
                                                  compute_type="auto", intra_threads=2)

    def translate(self, text):
        pieces = self.tokens.encode(text, out_type=str)
        result = self.translator.translate_batch([pieces], beam_size=3)[0]
        return self.tokens.decode(result.hypotheses[0]).strip()


def mono16(data, channels):
    if channels == 1:
        return data
    frames = np.frombuffer(data, dtype="<i2").reshape(-1, channels)
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


def capture(audio, device, language, target, stop, emit, record_path, speaker_model=None):
    """Capture continuously while speech recognition and translation consume queued blocks."""
    chunks = queue.Queue(maxsize=200)
    overflow = threading.Event()
    rate = int(device["defaultSampleRate"])
    channels = int(device["maxInputChannels"])
    decoder = KaldiRecognizer(language.speech, 16000)
    speakers = None
    if speaker_model is not None:
        decoder.SetSpkModel(speaker_model)
        speakers = SessionSpeakers()
    resampler = None
    partial = ""
    heard = False
    last_audio = time.monotonic()

    def callback(data, count, timing, flags):
        if flags & pa.paInputOverflow:
            overflow.set()
        try:
            chunks.put_nowait(data)
        except queue.Full:
            overflow.set()
        return None, pa.paContinue

    def publish(result):
        nonlocal partial
        phrase = json.loads(result)
        text = phrase.get("text", "").strip()
        if text:
            who = speakers.label(phrase) if speakers is not None else None
            emit("line", target, (text, language.translate(text), who))
        partial = ""
        emit("partial", target, "")

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
            stream.start_stream()
        emit("ready", target, None)
        while True:
            if stop.is_set() and stream.is_active():
                stream.stop_stream()
            try:
                data = chunks.get(timeout=0.1)
            except queue.Empty:
                if stop.is_set():
                    break
                if not stream.is_active():
                    raise RuntimeError("Аудиоустройство отключено.")
                # Some WASAPI endpoints send no packets during silence.
                if heard and time.monotonic() - last_audio > 0.8:
                    publish(decoder.FinalResult())
                    decoder.Reset()
                    heard = False
                continue
            if overflow.is_set():
                raise RuntimeError("Переполнен буфер звука. Закройте тяжёлые приложения и повторите запуск.")
            last_audio = time.monotonic()
            pcm, resampler = audioop.ratecv(mono16(data, channels), 2, 1, rate, 16000, resampler)
            if writer:
                writer.writeframesraw(pcm)
            heard = True
            if decoder.AcceptWaveform(pcm):
                publish(decoder.Result())
            else:
                current = json.loads(decoder.PartialResult()).get("partial", "")
                if current != partial:
                    partial = current
                    emit("partial", target, partial)
        if heard:
            publish(decoder.FinalResult())
