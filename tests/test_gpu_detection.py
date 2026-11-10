from unittest.mock import patch
from types import SimpleNamespace

from gpu_detection import nvidia_memory


def test_cuda_visible_device_selects_same_gpu_as_model():
    with patch.dict('os.environ', {'CUDA_VISIBLE_DEVICES': '2,0'}), \
         patch('pathlib.Path.is_file', return_value=True), \
         patch('subprocess.run', return_value=SimpleNamespace(stdout='12000, 8000\n')) as run:
        assert nvidia_memory() == (12000, 8000)
        assert '--id=2' in run.call_args.args[0]


def test_disabled_cuda_is_not_detected():
    with patch.dict('os.environ', {'CUDA_VISIBLE_DEVICES': ''}), patch('subprocess.run') as run:
        assert nvidia_memory() is None
        run.assert_not_called()
