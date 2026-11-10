import tempfile
import unittest
from pathlib import Path
from settings import read_split_level, save_split_level, read_preferences, save_preferences


class SettingsTests(unittest.TestCase):
    def test_saving_segmentation_preserves_device_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            save_preferences(path, {'devices': ['mic', 'speaker'], 'source_mode': 'Микрофон'})
            save_split_level(path, 8)
            self.assertEqual(read_preferences(path)['devices'], ['mic', 'speaker'])
            self.assertEqual(read_split_level(path), 8)
    def test_default_save_and_invalid_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            self.assertEqual(read_split_level(path), 5)
            save_split_level(path, 9)
            self.assertEqual(read_split_level(path), 9)
            with self.assertRaises(ValueError): save_split_level(path, 11)
            path.write_text('{invalid', encoding='utf-8')
            self.assertEqual(read_split_level(path), 5)
