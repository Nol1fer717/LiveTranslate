import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from engine import capture


class CaptureTests(unittest.TestCase):
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
