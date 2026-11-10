import os
import sqlite3
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
    def bind(self, *args, **kwargs): pass
    def destroy(self): pass
    def tk_popup(self, *args): pass
    def grab_release(self): pass

class NoteMouseTests(unittest.TestCase):
    def test_autosave_does_not_reorder_note_list(self):
        self.ui.add_note(); first=self.ui.current_note
        self.ui.title.delete(0,'end'); self.ui.title.insert(0,'Первая'); self.ui.save_current()
        self.ui.add_note(); second=self.ui.current_note
        self.ui.title.delete(0,'end'); self.ui.title.insert(0,'Вторая'); self.ui.save_current()
        self.ui.show_note(first); before=list(self.ui.note_ids)
        self.ui.body.insert('end','Изменение'); self.ui.save_current()
        self.assertEqual(self.ui.note_ids,before)
        self.assertIn(second,self.ui.note_ids)
    def test_failed_note_load_restores_autosave_and_keeps_previous_note(self):
        self.ui.add_note(); current=self.ui.current_note
        self.ui.body.insert('1.0', 'Старый текст'); self.ui.save_current()
        with patch.object(self.ui.store, 'note', side_effect=sqlite3.OperationalError('unavailable')), patch('library_ui.messagebox.showerror') as error:
            self.ui.show_note(999)
        error.assert_called_once()
        self.assertFalse(self.ui.loading)
        self.assertEqual(self.ui.current_note, current)
        self.assertEqual(self.ui.body.get('1.0', 'end-1c'), 'Старый текст')
        self.ui.body.insert('end', ' дополнение'); self.ui.changed(); self.ui.save_current()
        self.assertEqual(self.ui.store.note(current)[1], 'Старый текст дополнение')
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'LOCALAPPDATA':self.tmp.name, 'LIVETRANSLATE_DOCUMENTS':os.path.join(self.tmp.name, 'Documents')}); self.env.start()
        self.devices = patch('app.devices', return_value=([], [])); self.devices.start()
        self.root = tk.Tk(); self.app = App(self.root); self.root.update()
        self.ui = self.app.library
        self.ui.notes_page.master.select(self.ui.notes_page); self.root.update()
    def tearDown(self):
        self.app.finish_close(); self.devices.stop(); self.env.stop(); self.tmp.cleanup()

    def test_rounded_button_hover_keeps_expanded_width(self):
        from rounded_button import RoundedButton
        window = tk.Toplevel(self.root, bg='#ffffff'); window.geometry('600x80')
        button = RoundedButton(window, text='Тест', bg='#eeeeee')
        button.pack(fill='x'); self.root.update()
        width = button.winfo_width()
        button._enter(None)
        self.assertGreaterEqual(button._rounded_image.width(), width - 2)
        button._leave(None)
        self.assertGreaterEqual(button._rounded_image.width(), width - 2)
        window.destroy()

    def test_shortcuts_in_note_and_readonly_history(self):
        from clipboard_shortcuts import clipboard_shortcut
        self.ui.add_note(); self.ui.body.insert('1.0', 'Привет')
        body = self.ui.body
        self.assertEqual(clipboard_shortcut(SimpleNamespace(widget=body, keycode=65, state=4)), 'break')
        self.assertEqual(clipboard_shortcut(SimpleNamespace(widget=body, keycode=67, state=4)), 'break')
        self.assertEqual(body.clipboard_get(), 'Привет')
        body.mark_set('insert', 'end-1c'); body.tag_remove('sel', '1.0', 'end')
        self.assertEqual(clipboard_shortcut(SimpleNamespace(widget=body, keycode=86, state=4)), 'break')
        self.assertEqual(body.get('1.0', 'end-1c'), 'ПриветПривет')
        history = self.ui.session_text
        history.configure(state='normal'); history.delete('1.0', 'end'); history.insert('1.0', 'История'); history.configure(state='disabled')
        clipboard_shortcut(SimpleNamespace(widget=history, keycode=65, state=4))
        clipboard_shortcut(SimpleNamespace(widget=history, keycode=67, state=4))
        self.assertEqual(history.clipboard_get(), 'История')
        self.assertIsNone(clipboard_shortcut(SimpleNamespace(widget=history, keycode=86, state=4)))
        self.assertIsNone(clipboard_shortcut(SimpleNamespace(widget=body, keycode=86, state=12)))
        self.assertIsNone(clipboard_shortcut(SimpleNamespace(widget=body, keycode=86, state=0x20004)))

    def test_title_undo_is_confined_to_current_note(self):
        from clipboard_shortcuts import clipboard_shortcut
        self.ui.add_note(); first = self.ui.current_note
        self.ui.title.delete(0, 'end'); self.ui.title.insert(0, 'Заголовок A'); self.ui.save_current()
        self.ui.add_note(); second = self.ui.current_note
        self.ui.title.delete(0, 'end'); self.ui.title.insert(0, 'Заголовок B'); self.ui.save_current()
        self.ui.show_note(first); self.ui.show_note(second)
        self.ui.title.insert('end', '!')
        self.assertEqual(clipboard_shortcut(SimpleNamespace(widget=self.ui.title, keycode=90, state=4)), 'break')
        self.assertEqual(self.ui.title.get(), 'Заголовок B')
        clipboard_shortcut(SimpleNamespace(widget=self.ui.title, keycode=90, state=4))
        self.assertEqual(self.ui.title.get(), 'Заголовок B')

    def test_undo_does_not_restore_previous_note(self):
        self.ui.add_note(); first = self.ui.current_note
        self.ui.body.insert('1.0', 'NOTE A'); self.ui.save_current()
        self.ui.add_note(); second = self.ui.current_note
        self.ui.body.insert('1.0', 'NOTE B'); self.ui.save_current()
        self.ui.show_note(first); self.ui.show_note(second)
        for _ in range(2):
            try: self.ui.body.edit_undo()
            except tk.TclError: pass
        self.assertEqual(self.ui.body.get('1.0', 'end-1c'), 'NOTE B')

    def test_renaming_folder_preserves_current_note_folder(self):
        with patch('library_ui.simpledialog.askstring', return_value='Old'):
            self.ui.add_folder()
        folder = self.ui.selected_folder(); self.ui.add_note(); note = self.ui.current_note
        with patch('library_ui.simpledialog.askstring', return_value='New'):
            self.ui.rename_folder()
        self.ui.save_current()
        self.assertEqual(self.ui.store.note(note)[2], folder)

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


from clipboard_shortcuts import clipboard_shortcut


class ClipboardShortcutTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.root.withdraw()
        self.text = tk.Text(self.root)
        self.text.pack()
        self.text.insert('1.0', 'hello')
        self.text.tag_add('sel', '1.0', '1.5')
        self.text.focus_force()
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def test_windows_altgr_state_is_not_intercepted(self):
        self.root.clipboard_clear()
        result = clipboard_shortcut(SimpleNamespace(widget=self.text, state=0x20004, keycode=67))
        self.assertIsNone(result)
        with self.assertRaises(tk.TclError):
            self.root.clipboard_get()

    def test_ctrl_copy_still_copies_selection(self):
        self.root.clipboard_clear()
        result = clipboard_shortcut(SimpleNamespace(widget=self.text, state=0x0004, keycode=67))
        self.assertEqual(result, 'break')
        self.assertEqual(self.root.clipboard_get(), 'hello')

if __name__ == '__main__': unittest.main()
