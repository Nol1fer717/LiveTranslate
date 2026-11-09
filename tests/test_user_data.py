import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from storage import Storage
from user_data import migrate_user_data

class MigrationTests(unittest.TestCase):
    def test_moves_database_and_wav_by_copy_without_removing_originals(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA': tmp, 'LIVETRANSLATE_DOCUMENTS': str(Path(tmp) / 'Documents')}):
            old = Path(tmp) / 'LiveTranslate'; old.mkdir()
            legacy = Storage(old / 'library.sqlite3'); folder = legacy.add_folder('Original'); note = legacy.add_note(folder); legacy.save_note(note, 'Hello', 'Привет', folder); legacy.close()
            wav = old / 'Recordings' / 'session' / 'audio.wav'; wav.parent.mkdir(parents=True); wav.write_bytes(b'wave-data')
            migrated = Storage(); self.assertEqual(migrated.note(note)[1], 'Привет'); migrated.close()
            new = Path(tmp) / 'Documents' / 'LiveTranslate'
            self.assertEqual((new / 'Recordings' / 'session' / 'audio.wav').read_bytes(), b'wave-data')
            self.assertTrue(wav.exists()); self.assertTrue((old / 'library.sqlite3').exists())
            (new / 'Recordings' / 'session' / 'audio.wav').write_bytes(b'new-data')
            migrate_user_data()
            self.assertEqual((new / 'Recordings' / 'session' / 'audio.wav').read_bytes(), b'new-data')
            self.assertEqual(wav.read_bytes(), b'wave-data')
            (new / 'Recordings' / 'session' / 'audio.wav').unlink()
            migrate_user_data()
            self.assertFalse((new / 'Recordings' / 'session' / 'audio.wav').exists())

    def test_backup_reads_committed_wal_without_closing_original(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA': tmp, 'LIVETRANSLATE_DOCUMENTS': str(Path(tmp) / 'Documents')}):
            old = Path(tmp) / 'LiveTranslate'; old.mkdir()
            legacy = Storage(old / 'library.sqlite3')
            legacy.db.execute('PRAGMA journal_mode=WAL')
            legacy.add_folder('Committed before migration')
            migrated = Storage()
            self.assertEqual(migrated.folders()[0][1], 'Committed before migration')
            migrated.close(); legacy.close()

    def test_conflicting_recording_is_copied_under_distinct_name(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA': tmp, 'LIVETRANSLATE_DOCUMENTS': str(Path(tmp) / 'Documents')}):
            old = Path(tmp) / 'LiveTranslate' / 'Recordings' / 'test.wav'
            old.parent.mkdir(parents=True); old.write_bytes(b'old')
            target = Path(tmp) / 'Documents' / 'LiveTranslate' / 'Recordings' / 'test.wav'
            target.parent.mkdir(parents=True); target.write_bytes(b'new')
            migrate_user_data()
            self.assertEqual(target.read_bytes(), b'new')
            self.assertEqual(sorted(p.read_bytes() for p in target.parent.glob('*.wav')), [b'new', b'old'])

    def test_interrupted_recording_copy_can_be_retried(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA': tmp, 'LIVETRANSLATE_DOCUMENTS': str(Path(tmp) / 'Documents')}):
            wav = Path(tmp) / 'LiveTranslate' / 'Recordings' / 'test.wav'
            wav.parent.mkdir(parents=True); wav.write_bytes(b'recording')
            target = Path(tmp) / 'Documents' / 'LiveTranslate' / 'Recordings' / 'test.wav'
            with patch('user_data.shutil.copyfileobj', side_effect=OSError('disk error')):
                with self.assertRaises(OSError): migrate_user_data()
            self.assertFalse(target.exists())
            self.assertEqual(wav.read_bytes(), b'recording')
            migrate_user_data()
            self.assertEqual(target.read_bytes(), b'recording')

    def test_does_not_replace_existing_library(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA': tmp, 'LIVETRANSLATE_DOCUMENTS': str(Path(tmp) / 'Documents')}):
            old = Path(tmp) / 'LiveTranslate'; old.mkdir()
            legacy = Storage(old / 'library.sqlite3'); legacy.add_folder('Old'); legacy.close()
            new = Path(tmp) / 'Documents' / 'LiveTranslate'; new.mkdir(parents=True)
            current = Storage(new / 'library.sqlite3'); current.add_folder('Current'); current.close()
            migrated = Storage(); self.assertTrue(migrated.legacy_conflict); self.assertEqual([x[1] for x in migrated.folders()], ['Current']); migrated.close()
            legacy = Storage(old / 'library.sqlite3'); self.assertEqual([x[1] for x in legacy.folders()], ['Old']); legacy.close()

if __name__ == '__main__': unittest.main()
