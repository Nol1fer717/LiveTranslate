import tempfile
import unittest
from pathlib import Path
from storage import Storage

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'library.sqlite3'
        self.store = Storage(self.path)

    def tearDown(self):
        self.store.close(); self.tmp.cleanup()

    def test_sessions_persist_separately_and_delete_cascades(self):
        first = self.store.start_session('Микрофон')
        entry = {'time':'12:00:00', 'index':0, 'speaker':None, 'from':'EN', 'to':'RU', 'source':'Hello', 'target':'Привет'}
        self.store.add_phrase(first, entry); self.store.end_session(first)
        second = self.store.start_session('Звук компьютера')
        self.store.close(); self.store = Storage(self.path)
        self.assertEqual(self.store.phrases(first)[0][-2:], ('Hello', 'Привет'))
        self.assertEqual(self.store.phrases(second), [])
        self.assertIsNotNone(self.store.sessions()[1][2])
        self.store.delete_session(first)
        self.assertEqual(self.store.phrases(first), [])
        self.assertEqual([s[0] for s in self.store.sessions()], [second])

    def test_folder_rename_move_sort_and_delete_preserves_notes(self):
        folder = self.store.add_folder('Разговор 1')
        note = self.store.add_note(folder)
        self.store.save_note(note, 'Фраза', 'Hello — привет', folder)
        self.store.rename_folder(folder, 'Друг')
        self.store.close(); self.store = Storage(self.path)
        self.assertEqual(self.store.folders(), [(folder, 'Друг')])
        self.assertEqual(self.store.note(note), ('Фраза', 'Hello — привет', folder))
        self.assertEqual(self.store.notes(folder, 'По названию')[0][0], note)
        self.store.delete_folder(folder)
        self.assertIsNone(self.store.note(note)[2])
        self.assertEqual(self.store.notes(None, 'Сначала новые')[0][0], note)
        self.store.delete_note(note)
        self.assertEqual(self.store.notes('all', 'Сначала новые'), [])

if __name__ == '__main__': unittest.main()
