import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace

import numpy as np
from engine import capture, mono16


class CaptureTests(unittest.TestCase):
    def test_stuck_recognizer_requires_restart_and_suppresses_late_output(self):
        from whisper_stream import StuckRecognizerError
        entered = threading.Event(); release = threading.Event(); finished = threading.Event()
        stop = threading.Event(); events = []
        device = dict(name='Test', index=1, maxInputChannels=1, defaultSampleRate=16000)
        class Recognizer:
            def __init__(self, *args, **kwargs): self.emit = args[4]
            def accept(self, pcm):
                entered.set(); release.wait(3); self.emit('late', 'late', None); finished.set()
            def flush(self): pass
            def close(self): return True
        class Audio:
            def get_device_info_by_index(self, index): return device
            def open(self, **kwargs): self.callback = kwargs['stream_callback']; return self
            def start_stream(self):
                self.active = True
                def feed():
                    self.callback(bytes(3200), 1600, None, 0)
                    entered.wait(2); stop.set()
                self.worker = threading.Thread(target=feed); self.worker.start()
            def is_active(self): return self.active
            def stop_stream(self): self.active = False
            def close(self): self.worker.join()
        try:
            with patch('engine.WhisperStream', Recognizer), patch('engine.STOP_WAIT_SECONDS', .05):
                with self.assertRaises(StuckRecognizerError) as error:
                    capture(Audio(), device, {}, 0, stop, lambda *args: events.append(args), None, whisper=object())
            self.assertTrue(error.exception.restart_required)
        finally:
            release.set()
        self.assertTrue(finished.wait(2))
        self.assertFalse(any(event[0] == 'line' for event in events))
    def test_device_open_failure_closes_speech_workers(self):
        device=dict(name='Test',index=1,maxInputChannels=1,defaultSampleRate=16000)
        audio=Mock(); audio.get_device_info_by_index.return_value=device
        audio.open.side_effect=OSError('device unavailable')
        recognizer=Mock()
        with patch('engine.WhisperStream',return_value=recognizer):
            with self.assertRaises(OSError):
                capture(audio,device,{},0,threading.Event(),lambda *args:None,None,whisper=object())
        recognizer.close.assert_called_once()
    def test_unrecognized_audio_retains_queued_packets_in_order(self):
        from whisper_stream import UnrecognizedAudioError
        entered=threading.Event(); release=threading.Event(); stop=threading.Event()
        device=dict(name='Test', index=1, maxInputChannels=1, defaultSampleRate=16000)
        packets=[(n.to_bytes(2, 'little') * 1600) for n in (100, 200, 300)]
        class Recognizer:
            def accept(self, pcm):
                entered.set(); release.wait(2); raise UnrecognizedAudioError(pcm)
            def flush(self): pass
            def close(self): pass
        class Audio:
            def get_device_info_by_index(self, index): return device
            def open(self, **kwargs): self.callback=kwargs['stream_callback']; return self
            def start_stream(self):
                self.active=True
                def feed():
                    self.callback(packets[0],1600,None,0)
                    if entered.wait(2):
                        for packet in packets[1:]: self.callback(packet,1600,None,0)
                        time.sleep(.2)
                    release.set()
                self.worker=threading.Thread(target=feed); self.worker.start()
            def is_active(self): return self.active
            def stop_stream(self): self.active=False
            def close(self): self.worker.join()
        with patch('engine.WhisperStream', return_value=Recognizer()):
            with self.assertRaises(UnrecognizedAudioError) as error:
                capture(Audio(), device, {}, 0, stop, lambda *args: None, None, whisper=object())
        self.assertEqual(error.exception.pcm, b''.join(packets))
    def test_source_stop_does_not_cancel_other_source(self):
        from engine import SourceStop
        session = threading.Event(); first = SourceStop(session); second = SourceStop(session)
        first.set()
        self.assertTrue(first.is_set()); self.assertFalse(second.is_set()); self.assertFalse(session.is_set())
        session.set(); self.assertTrue(second.is_set())
    def test_manual_mode_emits_partial_translation_before_final(self):
        stop = threading.Event(); preview = threading.Event(); events = []
        device = dict(name='Test', index=1, maxInputChannels=1, defaultSampleRate=16000)
        class Decoder:
            def __init__(self, *args): pass
            def AcceptWaveform(self, data): return False
            def PartialResult(self): return '{"partial":"hello there"}'
            def FinalResult(self): return '{"text":"hello there"}'
            def Reset(self): pass
        class Audio:
            def get_device_info_by_index(self, index): return device
            def open(self, **kwargs): self.callback = kwargs['stream_callback']; return self
            def start_stream(self):
                self.active = True
                def feed():
                    for _ in range(2): self.callback(bytes(3200), 1600, None, 0); time.sleep(.05)
                    preview.wait(2); stop.set()
                self.worker = threading.Thread(target=feed); self.worker.start()
            def is_active(self): return self.active
            def stop_stream(self): self.active = False
            def close(self): self.worker.join()
        def emit(kind, index, value):
            events.append((kind, value))
            if kind == 'preview' and value and value[1]: preview.set()
        language = SimpleNamespace(source='en', speech=object(), translate=lambda text: 'привет')
        with patch('engine.KaldiRecognizer', Decoder):
            capture(Audio(), device, language, 0, stop, emit, None)
        self.assertTrue(preview.is_set())
        self.assertTrue(any(kind == 'line' for kind, value in events))
    def test_surround_loopback_uses_front_channels_without_attenuation(self):
        frames = np.array([[12000, 8000, 0, 0, 0, 0, 0, 0]], dtype="<i2")
        self.assertEqual(np.frombuffer(mono16(frames.tobytes(), 8, True), "<i2").tolist(), [10000])
        self.assertEqual(np.frombuffer(mono16(frames.tobytes(), 8), "<i2").tolist(), [10000])

    def test_surround_loopback_keeps_center_channel(self):
        frames = np.array([[0, 0, 12000, 0, 0, 0]], dtype="<i2")
        self.assertEqual(np.frombuffer(mono16(frames.tobytes(), 6, True), "<i2").tolist(), [12000])
    def test_wav_keeps_audio_and_silence_while_recognizer_is_blocked(self):
        block = bytes.fromhex("1000") * 1600
        stalled = threading.Event()
        release = threading.Event()
        saved = threading.Event()
        stop = threading.Event()
        device = dict(name="Recording", index=1, maxInputChannels=1, defaultSampleRate=16000)

        class Recognizer:
            def accept(self, pcm):
                stalled.set()
                if not release.wait(5):
                    raise TimeoutError("WAV writer did not run while inference was blocked")

            def flush(self):
                pass

            def close(self):
                pass

        class Device:
            def get_device_info_by_index(self, index):
                return device

            def open(self, **options):
                self.callback = options["stream_callback"]
                return self

            def start_stream(self):
                self.active = True

                def feed():
                    try:
                        self.callback(block, 1600, None, 0)
                        if not stalled.wait(2):
                            return
                        time.sleep(0.5)
                        for _ in range(8):
                            self.callback(block, 1600, None, 0)
                            time.sleep(0.1)
                        if path.stat().st_size > len(block) * 8:
                            saved.set()
                    finally:
                        stop.set()
                        release.set()

                self.thread = threading.Thread(target=feed)
                self.thread.start()

            def is_active(self):
                return self.active

            def stop_stream(self):
                self.active = False

            def close(self):
                self.thread.join()

        with tempfile.TemporaryDirectory() as temp, patch("engine.WhisperStream", return_value=Recognizer()):
            path = Path(temp) / "system.wav"
            capture(Device(), device, {}, 1, stop, lambda *args: None, path, whisper=object())
            self.assertTrue(saved.is_set())
            with wave.open(str(path)) as recording:
                pcm = recording.readframes(recording.getnframes())
            self.assertEqual(pcm.count(bytes.fromhex("1000")), 9 * 1600)
            self.assertIn(bytes(2 * 4000), pcm)
