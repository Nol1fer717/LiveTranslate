"""Local, incremental text translation with a single background worker."""
import queue
import threading
import tkinter as tk
from tkinter import ttk
from engine import DATA, GermanTranslation, Language
from theme import BG, CARD, TEXT, MUTED, BORDER, SELECTION

DIRECTIONS = {'Русский → Английский': 'ru', 'Английский → Русский': 'en', 'Немецкий → Русский': 'de'}

class TranslatorUI:
    def __init__(self, tabs):
        self.page = tk.Frame(tabs, bg=BG, padx=28, pady=20)
        tabs.add(self.page, text='Переводчик')
        self.page.columnconfigure(0, weight=1); self.page.columnconfigure(1, weight=1); self.page.rowconfigure(3, weight=1)
        tk.Label(self.page, text='Переводчик', bg=BG, fg=TEXT, font=('Segoe UI', 19, 'bold')).grid(row=0, column=0, sticky='w')
        tk.Label(self.page, text='Локальный перевод · текст остаётся на компьютере', bg=BG, fg=MUTED).grid(row=1, column=0, columnspan=2, sticky='w', pady=(3, 12))
        controls = tk.Frame(self.page, bg=BG); controls.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        tk.Label(controls, text='Направление', bg=BG, fg=MUTED).pack(side='left', padx=(0, 8))
        self.direction = ttk.Combobox(controls, values=list(DIRECTIONS), state='readonly', width=28, style='Dark.TCombobox')
        self.direction.current(0); self.direction.pack(side='left'); self.direction.bind('<<ComboboxSelected>>', self.changed)
        self.input = self.text_panel(0, 'Исходный текст'); self.output = self.text_panel(1, 'Перевод'); self.output.configure(state='disabled')
        self.input.bind('<<Modified>>', self.modified)
        self.input.bind('<Button-3>', self.context_menu)
        self.output.bind('<Button-3>', self.context_menu)
        self.status = tk.StringVar(value='Введите текст — перевод появится автоматически')
        tk.Label(self.page, textvariable=self.status, bg=BG, fg=MUTED, anchor='w').grid(row=4, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        self.requests = queue.Queue(maxsize=1); self.results = queue.SimpleQueue()
        self.generation = 0; self.debounce = None; self.closed = False; self.cache = {}
        self.job = self.page.after(100, self.poll)
        threading.Thread(target=self.worker, daemon=True).start()

    def text_panel(self, column, label):
        pane = tk.Frame(self.page, bg=CARD, highlightthickness=1, highlightbackground=BORDER, padx=14, pady=12)
        pane.grid(row=3, column=column, sticky='nsew', padx=(0,6) if column==0 else (6,0)); pane.columnconfigure(0, weight=1); pane.rowconfigure(1, weight=1)
        tk.Label(pane, text=label, bg=CARD, fg=MUTED, font=('Segoe UI',10,'bold')).grid(row=0,column=0,sticky='w',pady=(0,8))
        widget = tk.Text(pane, wrap='word', bg=CARD, fg=TEXT, insertbackground=TEXT, selectbackground=SELECTION, selectforeground=TEXT, relief='flat', font=('Segoe UI',12), undo=True)
        widget.grid(row=1,column=0,sticky='nsew'); scroll=ttk.Scrollbar(pane,command=widget.yview,style='Vertical.TScrollbar'); scroll.grid(row=1,column=1,sticky='ns'); widget.configure(yscrollcommand=scroll.set)
        return widget

    def context_menu(self, event):
        widget = event.widget
        editable = widget is self.input
        selected = bool(widget.tag_ranges('sel'))
        if editable and not selected:
            widget.mark_set('insert', f'@{event.x},{event.y}')
        menu = tk.Menu(widget, tearoff=False)
        if editable:
            menu.add_command(label='Вырезать', state='normal' if selected else 'disabled',
                             command=lambda: self.clipboard_action(widget, '<<Cut>>'))
        menu.add_command(label='Копировать', state='normal' if selected else 'disabled',
                         command=lambda: self.clipboard_action(widget, '<<Copy>>'))
        if editable:
            try:
                widget.clipboard_get(); paste_state = 'normal'
            except tk.TclError:
                paste_state = 'disabled'
            menu.add_command(label='Вставить', state=paste_state,
                             command=lambda: self.clipboard_action(widget, '<<Paste>>'))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'

    def clipboard_action(self, widget, action):
        widget.focus_set()
        widget.event_generate(action)

    def modified(self, event=None):
        if self.input.edit_modified():
            self.input.edit_modified(False); self.changed()

    def changed(self, event=None):
        self.generation += 1
        if self.debounce is not None: self.page.after_cancel(self.debounce); self.debounce = None
        text = self.input.get('1.0','end-1c').strip()
        self.set_output('')
        if not text:
            self.status.set('Введите текст — перевод появится автоматически'); return
        self.status.set('Ожидаем завершения ввода…')
        self.debounce = self.page.after(400, self.submit)

    def submit(self):
        if self.debounce is not None: self.page.after_cancel(self.debounce)
        self.debounce = None
        item = (self.generation, self.input.get('1.0','end-1c').strip(), DIRECTIONS[self.direction.get()])
        if self.requests.full():
            try: self.requests.get_nowait()
            except queue.Empty: pass
        self.requests.put_nowait(item)
        self.status.set('Переводим…')

    def worker(self):
        while True:
            item = self.requests.get()
            if item is None: return
            generation, text, source = item
            try:
                if source == 'de':
                    if not (DATA / 'translate-de_en-1_9').is_dir():
                        raise FileNotFoundError('Немецкая модель не установлена. Выберите её в установщике.')
                    if 'en' not in self.cache: self.cache['en'] = Language('en', load_speech=False)
                    if 'de' not in self.cache: self.cache['de'] = GermanTranslation(self.cache['en'])
                elif source not in self.cache:
                    self.cache[source] = Language(source, load_speech=False)
                self.results.put((generation, True, self.cache[source].translate(text)))
            except Exception as exc:
                self.results.put((generation, False, str(exc) if isinstance(exc, FileNotFoundError) else 'Не удалось загрузить модель перевода. Проверьте установку приложения.'))

    def set_output(self, text):
        self.output.configure(state='normal'); self.output.delete('1.0','end'); self.output.insert('1.0',text); self.output.configure(state='disabled')

    def poll(self):
        while not self.results.empty():
            generation, ok, result = self.results.get()
            if generation != self.generation: continue
            if ok: self.set_output(result); self.status.set('Перевод готов')
            else: self.set_output(''); self.status.set(result)
        self.job = self.page.after(100, self.poll)

    def close(self):
        self.closed = True
        if self.debounce is not None: self.page.after_cancel(self.debounce)
        if self.job is not None: self.page.after_cancel(self.job)
        if self.requests.full():
            try: self.requests.get_nowait()
            except queue.Empty: pass
        self.requests.put_nowait(None)
