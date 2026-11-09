import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gpu_detection import supports_turbo
from whisper_stream import load_whisper


class SelectionTests(unittest.TestCase):
    def test_hardware_limits(self):
        self.assertFalse(supports_turbo(None))
        self.assertFalse(supports_turbo((4096, 3500)))
        self.assertFalse(supports_turbo((16384, 4000)))
        self.assertTrue(supports_turbo((8192, 6000)))
        self.assertTrue(supports_turbo((8192, 1000), check_free=False))

    def test_turbo_falls_back_to_small_cuda_then_cpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); small = root/'small'; turbo = root/'turbo'; small.mkdir(); turbo.mkdir()
            attempts = []
            class Model:
                def __init__(self, folder, device, **kwargs):
                    attempts.append((Path(folder).name, device))
                    if folder == str(turbo) or device == 'cuda': raise RuntimeError('unavailable')
                def transcribe(self, *args, **kwargs): return iter([]), None
            with patch('whisper_stream.ctranslate2.get_cuda_device_count', return_value=1), patch('whisper_stream.nvidia_memory', return_value=(16384, 10000)), patch('whisper_stream.WhisperModel', Model):
                model = load_whisper(small, turbo)
            self.assertEqual(attempts, [('turbo','cuda'),('small','cuda'),('small','cpu')])
            self.assertEqual(model.livetranslate_model_name, 'Small')

    def test_no_cuda_uses_only_small_cpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'turbo').mkdir(); attempts=[]
            class Model:
                def __init__(self, folder, device, **kwargs): attempts.append((Path(folder).name, device))
                def transcribe(self, *args, **kwargs): return iter([]), None
            with patch('whisper_stream.ctranslate2.get_cuda_device_count', return_value=0), patch('whisper_stream.WhisperModel', Model):
                load_whisper(root/'small', root/'turbo')
            self.assertEqual(attempts, [('small','cpu')])
