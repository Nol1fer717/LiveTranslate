import os
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app import App

class FakeMenu:
    created = None
    def __init__(self, *args, **kwargs):
        self.items = []; FakeMenu.created = self
    def add_command(self, **kwargs): self.items.append(kwargs)
    def add_separator(self): pass
    def tk_popup(self, *args): pass
    def grab_release(self): pass

class NoteMouseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'LOCALAPPDATA':self.tmp.name, 'LIVETRANSLATE_DOCUMENTS':os.path.join(self.tmp.name, 'Documents')}); self.env.start()
        self.devices = patch('app.devices', return_value=([], [])); self.devices.start()
        self.root = tk.Tk(); self.app = App(self.root); self.root.update()
        self.ui = self.app.library
        self.ui.notes_page.master.select(self.ui.notes_page); self.root.update()
    def tearDown(self):
        self.app.finish_close(); self.devices.stop(); self.env.stop(); self.tmp.cleanup()

    def test_navigation_and_editor_fit_minimum_window(self):
        self.root.geometry('760x600'); self.root.update()
        for widget in (self.ui.folder_list, self.ui.note_list, self.ui.title, self.ui.body):
            self.assertGreater(widget.winfo_width(), 100)
            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), self.root.winfo_rooty() + self.root.winfo_height())

    def test_folder_heading_count_and_empty_editor(self):
        self.assertEqual(self.ui.note_count.get(), '0')
        self.assertEqual(str(self.ui.delete_note_button['state']), 'disabled')
        with patch('library_ui.simpledialog.askstring', return_value='Разговор'):
            self.ui.add_folder()
        self.assertEqual(self.ui.note_heading.get(), 'Разговор')
        self.ui.add_note()
        self.assertEqual(self.ui.note_count.get(), '1')
        self.assertEqual(str(self.ui.delete_note_button['state']), 'normal')
        self.assertFalse(self.ui.empty_editor.winfo_ismapped())

    def test_right_click_note_and_blank_and_inline_rename(self):
        self.ui.add_note(); self.root.update()
        bounds = self.ui.note_list.bbox(0)
        event = SimpleNamespace(y=bounds[1]+2, x_root=0, y_root=0)
        with patch('library_ui.tk.Menu', FakeMenu): self.ui.note_context_menu(event)
        self.assertEqual([x['label'] for x in FakeMenu.created.items], ['Переименовать', 'Удалить'])
        self.ui.note_double_click(event); self.assertIsNotNone(self.ui.rename_editor)
        self.ui.rename_editor.delete(0, 'end'); self.ui.rename_editor.insert(0, 'Разговор'); self.ui.finish_inline_rename(True)
        self.assertEqual(self.ui.store.note(self.ui.current_note)[0], 'Разговор')
        event.y = self.ui.note_list.winfo_height()-2
        with patch('library_ui.tk.Menu', FakeMenu): self.ui.note_context_menu(event)
        self.assertEqual([x['label'] for x in FakeMenu.created.items], ['Добавить заметку'])

    def test_add_note_from_context_menu_creates_and_selects_it(self):
        event = SimpleNamespace(y=self.ui.note_list.winfo_height()-2, x_root=0, y_root=0)
        with patch('library_ui.tk.Menu', FakeMenu): self.ui.note_context_menu(event)
        FakeMenu.created.items[0]['command']()
        self.root.update()
        self.assertEqual(len(self.ui.store.notes('all', 'Сначала новые')), 1)
        self.assertIsNotNone(self.ui.current_note)
        self.assertEqual(self.ui.title.get(), 'Новая заметка')

    def test_add_folder_context_menu(self):
        event = SimpleNamespace(x_root=0, y_root=0)
        with patch('library_ui.tk.Menu', FakeMenu): self.ui.folder_context_menu(event)
        with patch('library_ui.simpledialog.askstring', return_value='Новая папка'):
            FakeMenu.created.items[0]['command']()
            self.root.update()
        self.assertEqual(self.ui.note_heading.get(), 'Новая папка')

    def test_rename_is_committed_when_editor_loses_focus(self):
        self.ui.add_note(); self.root.update()
        self.ui.rename_note_inline()
        self.ui.rename_editor.delete(0, 'end'); self.ui.rename_editor.insert(0, 'Слова для повторения')
        self.ui.finish_inline_rename(True)
        self.assertEqual(self.ui.store.note(self.ui.current_note)[0], 'Слова для повторения')

    def test_context_menu_selection_and_replacement(self):
        self.ui.add_note(); self.ui.body.insert('1.0', 'helllo world'); self.root.update()
        self.ui.body.tag_add('sel', '1.0', '1.6')
        bounds = self.ui.body.bbox('1.1')
        event = SimpleNamespace(widget=self.ui.body, x=bounds[0], y=bounds[1], x_root=0, y_root=0)
        with patch('library_ui.tk.Menu', FakeMenu), patch('library_ui.spelling_suggestions', return_value=['hello']): self.ui.editor_context_menu(event)
        self.assertEqual([x['label'] for x in FakeMenu.created.items], ['hello', 'Вырезать', 'Копировать', 'Вставить'])
        self.assertEqual(FakeMenu.created.items[2]['state'], 'normal')
        FakeMenu.created.items[0]['command']()
        self.assertEqual(self.ui.body.get('1.0', 'end-1c'), 'hello world')
        self.assertTrue(self.ui.save_current())
        self.assertEqual(self.ui.store.note(self.ui.current_note)[1], 'hello world')

if __name__ == '__main__': unittest.main()
