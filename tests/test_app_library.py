import os
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from app import App

class AppLibraryTests(unittest.TestCase):
    def test_session_events_and_notes_are_saved_on_close(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory}), patch('app.devices', return_value=([{'name':'Test microphone'}], [{'name':'Test output'}])):
            root = tk.Tk(); root.withdraw(); app = App(root)
            def session(selected, folder, stop, detect):
                app.events.put(('line', 0, ('Hello', 'Привет', None, 'EN → RU')))
                app.events.put(('done', None, None))
            app.session = session
            app.toggle()
            deadline = time.monotonic() + 5
            while app.stop is not None and time.monotonic() < deadline:
                root.update(); time.sleep(.02)
            self.assertIsNone(app.stop)
            app.history.tag_add('sel', '3.0', '3.3')
            selection = app.history.get('sel.first', 'sel.last')
            app.render()
            self.assertEqual(app.history.get('sel.first', 'sel.last'), selection)
            session_id = app.storage.sessions()[0][0]
            self.assertEqual(app.storage.phrases(session_id)[0][-2:], ('Hello', 'Привет'))
            app.library.add_note(); app.library.title.delete(0, 'end'); app.library.title.insert(0, 'Greetings')
            app.library.body.insert('1.0', 'Hello — Привет')
            note_id = app.library.current_note
            app.finish_close()
            from storage import Storage
            saved = Storage(os.path.join(directory, 'LiveTranslate', 'library.sqlite3'))
            self.assertEqual(saved.note(note_id)[:2], ('Greetings', 'Hello — Привет'))
            self.assertIsNotNone(saved.sessions()[0][2]); saved.close()

if __name__ == '__main__': unittest.main()
