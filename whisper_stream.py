from collections import deque
import json

import numpy as np
import webrtcvad
from faster_whisper import WhisperModel
from vosk import KaldiRecognizer


def load_whisper(folder):
    return WhisperModel(str(folder), device="cpu", compute_type="int8", cpu_threads=3,
                        num_workers=2, local_files_only=True)


class WhisperStream:
    """Detect and translate each utterance independently on this audio input."""
    FRAME_BYTES = 640  # 20 ms at 16 kHz, mono PCM16

    def __init__(self, model, languages, speaker_model, speakers, line, partial):
        self.model = model
        self.languages = languages
        self.speakers = speakers
        self.line = line
        self.partial = partial
        self.speaker_decoder = None
        if speaker_model is not None:
            self.speaker_decoder = KaldiRecognizer(languages["en"].speech, 16000, speaker_model)
        self.vad = webrtcvad.Vad(2)
        self.pending = bytearray()
        self.lead = deque(maxlen=10)
        self.frames = []
        self.voiced = 0
        self.quiet = 0

    def accept(self, pcm):
        self.pending.extend(pcm)
        while len(self.pending) >= self.FRAME_BYTES:
            frame = bytes(self.pending[:self.FRAME_BYTES])
            del self.pending[:self.FRAME_BYTES]
            speech = self.vad.is_speech(frame, 16000)
            if not self.frames:
                self.lead.append(frame)
                if not speech:
                    continue
                self.frames.extend(self.lead)
                self.lead.clear()
            else:
                self.frames.append(frame)
            self.voiced += int(speech)
            self.quiet = 0 if speech else self.quiet + 1
            if self.voiced == 6 and speech:
                self.partial("Слушаю…")
            if self.quiet >= 32 or len(self.frames) >= 600:
                self.finish()

    def finish(self):
        pcm = b"".join(self.frames)
        enough_speech = self.voiced >= 9
        self.frames.clear()
        self.quiet = self.voiced = 0
        if not enough_speech:
            self.partial("")
            return
        self.partial("Определяю язык…")
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        segments, info = self.model.transcribe(samples, task="transcribe", language=None,
                                              beam_size=3, temperature=0, condition_on_previous_text=False)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        if text:
            language = self.languages.get(info.language)
            translated = language.translate(text) if language else "Перевод доступен для русского и английского."
            who = None
            if self.speaker_decoder is not None:
                self.speaker_decoder.AcceptWaveform(pcm)
                who = self.speakers.label(json.loads(self.speaker_decoder.FinalResult()))
                self.speaker_decoder.Reset()
            tag = {"en": "EN → RU", "ru": "RU → EN"}.get(info.language, info.language.upper())
            self.line(text, translated, who, tag)
        self.partial("")

    def flush(self):
        if self.pending and self.frames:
            self.frames.append(bytes(self.pending))
        self.pending.clear()
        self.lead.clear()
        if self.frames:
            self.finish()
