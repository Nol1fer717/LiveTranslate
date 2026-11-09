import re
import sqlite3
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from windows_spelling import suggestions as spelling_suggestions
from rounded_button import RoundedButton
from theme import BG, CARD, FIELD, TEXT, MUTED, ACCENT, ACCENT_DARK, ACCENT_SOFT, BORDER, HOVER, SELECTION

BLUE = ACCENT
SOURCES = ('Микрофон', 'Звук компьютера')


def button(parent, label, command):
    return RoundedButton(parent, text=label, command=command, bg=FIELD, fg=TEXT, activebackground=HOVER, activeforeground=TEXT, relief='flat', padx=10, pady=6, cursor='hand2')


def listing(parent, **kwargs):
    return tk.Listbox(parent, bg=CARD, fg=TEXT, selectbackground=ACCENT_SOFT, selectforeground=TEXT,
                      relief='flat', highlightthickness=0, exportselection=False, font=('Segoe UI', 10), activestyle='none', **kwargs)


class LibraryUI:
    def __init__(self, tabs, storage):
        self.store = storage
        self.current_note = None
        self.active_session = lambda: None
        self.loading = False
        self.save_job = None
        self.rename_editor = None
        self.history_page = tk.Frame(tabs, bg=BG, padx=18, pady=16)
        self.notes_page = tk.Frame(tabs, bg=BG, padx=18, pady=16)
        tabs.add(self.history_page, text='История')
        tabs.add(self.notes_page, text='Заметки')
        self.build_history()
        self.build_notes()
        self.refresh_history()
        self.refresh_folders()

    def build_history(self):
        page = self.history_page
        page.columnconfigure(1, weight=1); page.rowconfigure(1, weight=1)
        tk.Label(page, text='Сеансы перевода', bg=BG, fg=TEXT, font=('Segoe UI', 16, 'bold')).grid(row=0, column=0, sticky='w', pady=(0, 12))
        left = tk.Frame(page, bg=BG); left.grid(row=1, column=0, sticky='nsew', padx=(0, 14))
        self.session_list = listing(left, width=29); self.session_list.pack(fill='both', expand=True)
        self.session_list.bind('<<ListboxSelect>>', self.show_session)
        button(left, 'Удалить сеанс', self.delete_session).pack(fill='x', pady=(8, 0))
        right = tk.Frame(page, bg=CARD); right.grid(row=1, column=1, sticky='nsew')
        self.session_text = tk.Text(right, wrap='word', bg=CARD, fg=TEXT, selectbackground=SELECTION, selectforeground=TEXT, relief='flat', padx=16, pady=14, font=('Segoe UI', 11))
        scroll = ttk.Scrollbar(right, command=self.session_text.yview); self.session_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); self.session_text.pack(fill='both', expand=True)
        self.session_text.tag_configure('meta', foreground=MUTED, spacing1=10)
        self.session_text.tag_configure('source', foreground=BLUE)
        self.session_text.configure(state='disabled')
        tk.Label(page, text='Выделите текст мышью и нажмите Ctrl+C, чтобы скопировать.', bg=BG, fg=MUTED).grid(row=2, column=1, sticky='w', pady=(8, 0))

    def refresh_history(self):
        old = self.session_ids[self.session_list.curselection()[0]] if getattr(self, 'session_ids', None) and self.session_list.curselection() else None
        sessions = self.store.sessions(); self.session_ids = [row[0] for row in sessions]
        self.session_list.delete(0, 'end')
        for _, started, ended, mode, count in sessions:
            self.session_list.insert('end', f"{started.replace('T', ' ')}  ·  {count} фраз" + ('' if ended else '  ·  не завершён'))
        if old in self.session_ids:
            pos = self.session_ids.index(old); self.session_list.selection_set(pos); self.show_session()
        elif sessions:
            self.session_list.selection_set(0); self.show_session()
        else:
            self._history_content('Сохранённых сеансов пока нет.')

    def _history_content(self, text):
        self.session_text.configure(state='normal'); self.session_text.delete('1.0', 'end'); self.session_text.insert('end', text); self.session_text.configure(state='disabled')

    def show_session(self, event=None):
        selected = self.session_list.curselection()
        if not selected: return
        phrases = self.store.phrases(self.session_ids[selected[0]])
        self.session_text.configure(state='normal'); self.session_text.delete('1.0', 'end')
        if not phrases: self.session_text.insert('end', 'В этом сеансе нет распознанных фраз.')
        for time, index, speaker, source_lang, target_lang, source, target in phrases:
            meta = ' · '.join(x for x in (time, SOURCES[index] if index in (0, 1) else '', speaker) if x)
            self.session_text.insert('end', meta + '\n', 'meta')
            self.session_text.insert('end', f'[{source_lang}]  {source}\n', 'source')
            self.session_text.insert('end', f'[{target_lang}]  {target}\n')
        self.session_text.configure(state='disabled')

    def delete_session(self):
        selected = self.session_list.curselection()
        if selected and self.session_ids[selected[0]] == self.active_session():
            messagebox.showinfo('История', 'Сначала остановите текущий сеанс.')
            return
        if selected and messagebox.askyesno('Удалить сеанс', 'Удалить этот сеанс из истории?'):
            self.store.delete_session(self.session_ids[selected[0]]); self.refresh_history()

    def build_notes(self):
        p = self.notes_page; p.columnconfigure(2, weight=1); p.rowconfigure(1, weight=1)
        tk.Label(p, text='Папки', bg=BG, fg=TEXT, font=('Segoe UI', 12, 'bold')).grid(row=0, column=0, sticky='w')
        tk.Label(p, text='Заметки', bg=BG, fg=TEXT, font=('Segoe UI', 12, 'bold')).grid(row=0, column=1, sticky='w')
        folders = tk.Frame(p, bg=BG); folders.grid(row=1, column=0, sticky='nsew', padx=(0, 10), pady=(10, 0))
        self.folder_list = listing(folders, width=20); self.folder_list.pack(fill='both', expand=True)
        self.folder_list.bind('<<ListboxSelect>>', self.folder_selected)
        for label, command in (('+ Папка', self.add_folder), ('Переименовать', self.rename_folder), ('Удалить папку', self.delete_folder)):
            button(folders, label, command).pack(fill='x', pady=(5, 0))
        notes = tk.Frame(p, bg=BG); notes.grid(row=1, column=1, sticky='nsew', padx=(0, 10), pady=(10, 0))
        self.sort = ttk.Combobox(notes, values=('Сначала новые', 'По названию'), state='readonly', width=20, style='Dark.TCombobox'); self.sort.current(0); self.sort.pack(fill='x', pady=(0, 6)); self.sort.bind('<<ComboboxSelected>>', lambda e: self.refresh_notes())
        self.note_list = listing(notes, width=23); self.note_list.pack(fill='both', expand=True); self.note_list.bind('<<ListboxSelect>>', self.note_selected)
        self.note_list.bind('<Button-3>', self.note_context_menu)
        self.note_list.bind('<Double-Button-1>', self.note_double_click)
        button(notes, '+ Заметка', self.add_note).pack(fill='x', pady=(5, 0)); button(notes, 'Удалить заметку', self.delete_note).pack(fill='x', pady=(5, 0))
        editor = tk.Frame(p, bg=CARD, padx=12, pady=12); editor.grid(row=1, column=2, sticky='nsew', pady=(10, 0)); editor.columnconfigure(0, weight=1); editor.rowconfigure(2, weight=1)
        self.title = tk.Entry(editor, bg=FIELD, fg=TEXT, insertbackground=TEXT, relief='flat', font=('Segoe UI', 14, 'bold'))
        self.title.grid(row=0, column=0, sticky='ew', pady=(0, 8), ipady=6); self.title.bind('<KeyRelease>', self.changed)
        move = tk.Frame(editor, bg=CARD); move.grid(row=1, column=0, sticky='ew', pady=(0, 8)); tk.Label(move, text='Папка:', bg=CARD, fg=MUTED).pack(side='left')
        self.move_folder = ttk.Combobox(move, state='readonly', style='Dark.TCombobox'); self.move_folder.pack(side='left', fill='x', expand=True, padx=(8, 0)); self.move_folder.bind('<<ComboboxSelected>>', self.changed)
        text_frame = tk.Frame(editor, bg=CARD); text_frame.grid(row=2, column=0, sticky='nsew')
        self.body = tk.Text(text_frame, wrap='word', undo=True, bg=CARD, fg=TEXT, insertbackground=TEXT, selectbackground=SELECTION, selectforeground=TEXT, relief='flat', font=('Segoe UI', 11))
        scroll = ttk.Scrollbar(text_frame, command=self.body.yview); self.body.configure(yscrollcommand=scroll.set); scroll.pack(side='right', fill='y'); self.body.pack(fill='both', expand=True)
        self.body.bind('<<Modified>>', self.body_changed)
        self.body.bind('<Button-3>', self.editor_context_menu)
        self.title.bind('<Button-3>', self.editor_context_menu)
        self.note_status = tk.StringVar(value='Выберите или создайте заметку')
        tk.Label(editor, textvariable=self.note_status, bg=CARD, fg=MUTED).grid(row=3, column=0, sticky='w', pady=(8, 0))
        self.enable_editor(False)

    def enable_editor(self, enabled):
        state = 'normal' if enabled else 'disabled'; self.title.configure(state=state, disabledbackground=FIELD, disabledforeground=MUTED); self.body.configure(state=state); self.move_folder.configure(state='readonly' if enabled else 'disabled')

    def selected_folder(self):
        sel = self.folder_list.curselection()
        return self.folder_ids[sel[0]] if sel else 'all'

    def refresh_folders(self, selected='all'):
        folders = self.store.folders(); self.folder_ids = ['all', None] + [x[0] for x in folders]
        self.folder_list.delete(0, 'end')
        for name in ['Все заметки', 'Без папки'] + [x[1] for x in folders]: self.folder_list.insert('end', name)
        self.move_ids = [None] + [x[0] for x in folders]; self.move_folder.configure(values=['Без папки'] + [x[1] for x in folders])
        pos = self.folder_ids.index(selected) if selected in self.folder_ids else 0; self.folder_list.selection_set(pos)
        self.refresh_notes()

    def folder_selected(self, event=None):
        if not self.save_current(): return
        self.current_note = None; self.refresh_notes(); self.show_note(None)

    def ask_folder(self, initial=''):
        name = simpledialog.askstring('Папка', 'Название папки:', initialvalue=initial, parent=self.notes_page)
        return name.strip() if name else ''

    def add_folder(self):
        name = self.ask_folder()
        if not name: return
        try: folder = self.store.add_folder(name)
        except sqlite3.IntegrityError: messagebox.showerror('Папка', 'Папка с таким названием уже существует.'); return
        if not self.save_current(): return
        self.refresh_folders(folder)

    def rename_folder(self):
        folder = self.selected_folder()
        if folder in ('all', None): return
        name = self.ask_folder(dict(self.store.folders())[folder])
        if not name: return
        try: self.store.rename_folder(folder, name)
        except sqlite3.IntegrityError: messagebox.showerror('Папка', 'Папка с таким названием уже существует.'); return
        if not self.save_current(): return
        self.refresh_folders(folder)

    def delete_folder(self):
        folder = self.selected_folder()
        if folder in ('all', None): return
        if messagebox.askyesno('Удалить папку', 'Удалить папку? Заметки сохранятся в разделе «Без папки».'):
            if not self.save_current(): return
            self.store.delete_folder(folder); self.current_note = None; self.refresh_folders(None); self.show_note(None)

    def refresh_notes(self, select=None):
        rows = self.store.notes(self.selected_folder(), self.sort.get()); self.note_ids = [x[0] for x in rows]
        self.note_list.delete(0, 'end')
        for _, title, _, _ in rows: self.note_list.insert('end', title)
        if select in self.note_ids: self.note_list.selection_set(self.note_ids.index(select))

    def note_at(self, event):
        index = self.note_list.nearest(event.y)
        bounds = self.note_list.bbox(index) if self.note_list.size() else None
        if bounds and bounds[1] <= event.y < bounds[1] + bounds[3]:
            return index
        return None

    def select_note_at(self, index):
        note = self.note_ids[index]
        if note != self.current_note:
            if not self.save_current():
                return False
            self.refresh_notes(note)
            self.show_note(note)
        else:
            self.note_list.selection_clear(0, 'end')
            self.note_list.selection_set(index)
        return True

    def note_context_menu(self, event):
        index = self.note_at(event)
        menu = tk.Menu(self.note_list, tearoff=False)
        if index is None:
            menu.add_command(label='Добавить заметку', command=self.add_note)
        elif self.select_note_at(index):
            menu.add_command(label='Переименовать', command=self.rename_note_inline)
            menu.add_command(label='Удалить', command=self.delete_note)
        else:
            return 'break'
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'

    def note_double_click(self, event):
        index = self.note_at(event)
        if index is not None and self.select_note_at(index):
            self.rename_note_inline()
        return 'break'

    def rename_note_inline(self):
        if self.current_note is None or not self.save_current():
            return
        selected = self.note_list.curselection()
        if not selected:
            return
        index = selected[0]
        self.note_list.see(index)
        bounds = self.note_list.bbox(index)
        if not bounds:
            return
        if self.rename_editor is not None:
            self.finish_inline_rename(False)
        x, y, width, height = bounds
        editor = tk.Entry(self.note_list, bg=FIELD, fg=TEXT, insertbackground=TEXT, relief='solid', font=('Segoe UI', 10))
        self.rename_editor = editor
        editor.place(x=x, y=y, width=max(width, self.note_list.winfo_width() - x), height=max(height, 22))
        editor.insert(0, self.note_list.get(index))
        editor.select_range(0, 'end')
        editor.bind('<Return>', lambda event: self.finish_inline_rename(True))
        editor.bind('<Escape>', lambda event: self.finish_inline_rename(False))
        editor.bind('<FocusOut>', lambda event: self.finish_inline_rename(True))
        editor.focus_set()

    def finish_inline_rename(self, save):
        editor = self.rename_editor
        if editor is None:
            return 'break'
        name = editor.get().strip()
        self.rename_editor = None
        editor.destroy()
        if save and name and self.current_note is not None:
            self.title.delete(0, 'end')
            self.title.insert(0, name)
            self.save_current()
        return 'break'

    def editor_context_menu(self, event):
        widget = event.widget
        if str(widget.cget('state')) == 'disabled':
            return 'break'
        menu = tk.Menu(widget, tearoff=False)
        selected = bool(widget.tag_ranges('sel')) if isinstance(widget, tk.Text) else bool(widget.selection_present())
        if not isinstance(widget, tk.Text) and not selected:
            widget.icursor(widget.index(f'@{event.x}'))
        if isinstance(widget, tk.Text):
            point = widget.index(f'@{event.x},{event.y}')
            if not selected:
                widget.mark_set('insert', point)
            line, column = map(int, point.split('.'))
            text = widget.get(f'{line}.0', f'{line}.end')
            for match in re.finditer(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", text, re.UNICODE):
                if match.start() <= column < match.end():
                    try:
                        suggestions = spelling_suggestions(match.group())
                    except (OSError, ValueError):
                        suggestions = []
                    for suggestion in suggestions:
                        start = f'{line}.{match.start()}'
                        end = f'{line}.{match.end()}'
                        menu.add_command(label=suggestion, command=lambda value=suggestion, first=start, last=end: self.replace_word(first, last, value))
                    if suggestions:
                        menu.add_separator()
                    break
        menu.add_command(label='Вырезать', state='normal' if selected else 'disabled', command=lambda: self.editor_action(widget, '<<Cut>>'))
        menu.add_command(label='Копировать', state='normal' if selected else 'disabled', command=lambda: self.editor_action(widget, '<<Copy>>'))
        try:
            widget.clipboard_get()
            paste_state = 'normal'
        except tk.TclError:
            paste_state = 'disabled'
        menu.add_command(label='Вставить', state=paste_state, command=lambda: self.editor_action(widget, '<<Paste>>'))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'

    def editor_action(self, widget, action):
        widget.focus_set()
        widget.event_generate(action)
        if action in ('<<Cut>>', '<<Paste>>'):
            widget.after_idle(self.changed)

    def replace_word(self, start, end, replacement):
        self.body.edit_separator()
        self.body.delete(start, end)
        self.body.insert(start, replacement)
        self.body.edit_separator()
        self.body.focus_set()

    def add_note(self):
        if not self.save_current(): return
        folder = self.selected_folder(); folder = None if folder == 'all' else folder
        note = self.store.add_note(folder); self.refresh_notes(note); self.show_note(note); self.title.focus_set(); self.title.select_range(0, 'end')

    def note_selected(self, event=None):
        sel = self.note_list.curselection()
        if not sel: return
        note = self.note_ids[sel[0]]
        if note != self.current_note:
            if not self.save_current(): return
            self.refresh_notes(note); self.show_note(note)

    def show_note(self, note):
        self.loading = True; self.enable_editor(True); self.title.delete(0, 'end'); self.body.delete('1.0', 'end'); self.current_note = note
        if note is None:
            self.note_status.set('Выберите или создайте заметку'); self.enable_editor(False)
        else:
            title, body, folder = self.store.note(note); self.title.insert(0, title); self.body.insert('1.0', body)
            self.move_folder.current(self.move_ids.index(folder) if folder in self.move_ids else 0); self.note_status.set('Сохранено')
        self.body.edit_modified(False); self.loading = False

    def body_changed(self, event=None):
        if self.body.edit_modified():
            self.body.edit_modified(False); self.changed()

    def changed(self, event=None):
        if self.loading or self.current_note is None: return
        self.note_status.set('Сохраняем…')
        if self.save_job: self.notes_page.after_cancel(self.save_job)
        self.save_job = self.notes_page.after(500, self.save_current)

    def save_current(self):
        if self.save_job: self.notes_page.after_cancel(self.save_job); self.save_job = None
        if self.current_note is None: return True
        folder_index = self.move_folder.current(); folder = self.move_ids[folder_index] if folder_index >= 0 else None
        try:
            title = self.title.get().strip() or 'Без названия'
            body = self.body.get('1.0', 'end-1c')
            if self.store.note(self.current_note) != (title, body, folder):
                self.store.save_note(self.current_note, title, body, folder)
        except (sqlite3.Error, OSError) as exc:
            self.note_status.set('Не сохранено')
            messagebox.showerror('Заметки', f'Не удалось сохранить заметку: {exc}', parent=self.notes_page)
            return False
        self.note_status.set('Сохранено'); self.refresh_notes(self.current_note)
        return True

    def delete_note(self):
        if self.current_note is not None and messagebox.askyesno('Удалить заметку', 'Удалить выбранную заметку?'):
            if self.save_job: self.notes_page.after_cancel(self.save_job); self.save_job = None
            self.store.delete_note(self.current_note); self.current_note = None; self.refresh_notes(); self.show_note(None)
