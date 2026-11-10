import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from model_readiness import base_models_ready, recover_stale_marker


class ModelReadinessTests(unittest.TestCase):
    def test_stale_marker_requires_verified_hashes_and_no_running_downloader(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); data=root/'data'; data.mkdir()
            file=data/'model.bin'; file.write_bytes(b'valid')
            marker=data/'.models-installing'; marker.touch()
            manifest=root/'packages.json'
            manifest.write_text(json.dumps([{'task':None,'files':[{'path':'data/model.bin','sha256':hashlib.sha256(b'valid').hexdigest()}]}]),encoding='utf-8')
            with patch('model_readiness.downloader_running', return_value=True):
                self.assertIsNone(recover_stale_marker(data, manifest))
                self.assertFalse(base_models_ready(data, manifest))
            with patch('model_readiness.downloader_running', return_value=False):
                self.assertTrue(recover_stale_marker(data, manifest))
                self.assertTrue(base_models_ready(data, manifest))
                file.write_bytes(b'corrupt')
                self.assertFalse(base_models_ready(data, manifest))
                self.assertFalse(recover_stale_marker(data, manifest))
    def test_incomplete_or_installing_models_are_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root / 'data'; data.mkdir()
            manifest = root / 'packages.json'
            manifest.write_text(json.dumps([{'task': None, 'files': [{'path': 'data/model.bin'}, {'path': 'data/conf/config.json'}]}]), encoding='utf-8')
            (data / 'model.bin').write_bytes(b'model')
            self.assertFalse(base_models_ready(data, manifest))
            (data / 'conf').mkdir(); (data / 'conf' / 'config.json').write_text('ok')
            self.assertTrue(base_models_ready(data, manifest))
            (data / '.models-installing').touch()
            self.assertFalse(base_models_ready(data, manifest))
