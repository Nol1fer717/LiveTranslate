import tempfile
import unittest
from pathlib import Path
from settings import read_split_level, save_split_level


class SettingsTests(unittest.TestCase):
    def test_default_save_and_invalid_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            self.assertEqual(read_split_level(path), 5)
            save_split_level(path, 9)
            self.assertEqual(read_split_level(path), 9)
            with self.assertRaises(ValueError): save_split_level(path, 11)
            path.write_text('{invalid', encoding='utf-8')
            self.assertEqual(read_split_level(path), 5)
