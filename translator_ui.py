"""Local, incremental text translation with a single background worker."""
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk
from engine import DATA, EnglishToGerman, GermanTranslation, Language
from theme import BG, CARD, TEXT, MUTED, BORDER, SELECTION

AUTO_LABEL = 'Автоматически'
DIRECTIONS = {AUTO_LABEL: 'auto', 'Русский → Немецкий': 'ru_de'}
LANGUAGE_LABELS = {'ru': 'Русский → Английский', 'en': 'Английский → Русский', 'de': 'Немецкий → Русский', 'ru_de': 'Русский → Немецкий'}
GERMAN_WORDS = {'hallo', 'danke', 'bitte', 'tschüss', 'guten tag', 'guten morgen', 'guten abend', 'auf wiedersehen'}


def detect_text_language(text, identifier):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return None, False
    russian = sum('а' <= c.lower() <= 'я' or c.lower() == 'ё' for c in letters)
    latin = sum('a' <= c.lower() <= 'z' or c.lower() in 'äöüß' for c in letters)
    if russian and latin:
        return None, False
    if russian == len(letters):
        return 'ru', False
    if latin != len(letters):
        return None, False
    normalized = text.strip().strip('.,!?;:«»"\' ').casefold()
    if any(c in normalized for c in 'äöüß') or normalized in GERMAN_WORDS:
        return 'de', False
    language, confidence = identifier.classify(text)
    if confidence < 0.8:
        return 'en', True
    return language, False

# Only unambiguous, standalone conversational questions are normalized.  A
# general punctuation guess would change the meaning of statements and fragments.
QUESTION_FORMS = {
    'ru': re.compile(r'(?:привет[, ]+)?(?:как дела|как у тебя дела|как у вас дела|как поживаешь|как поживаете|что случилось)', re.I),
    'en': re.compile(r"(?:(?:hi|hello|hey)[, ]+)?(?:how are you|how are you doing|what up|whats up|what['’]s up|what happened)", re.I),
    'de': re.compile(r"(?:wie geht es dir|wie geht es ihnen|wie geht['’]s|was ist passiert)", re.I),
}


def prepare_translation_text(text, source):
    text = text.strip()
    pattern = QUESTION_FORMS.get('ru' if source == 'ru_de' else source)
    if pattern and pattern.fullmatch(text):
        return text + '?'
    return text

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
        self.direction_mode = 'auto'
        self.direction.current(0); self.direction.pack(side='left'); self.direction.bind('<<ComboboxSelected>>', self.direction_selected)
        self.input = self.text_panel(0, 'Исходный текст'); self.output = self.text_panel(1, 'Перевод'); self.output.configure(state='disabled')
        self.input.bind('<<Modified>>', self.modified)
        self.input.bind('<Button-3>', self.context_menu)
        self.output.bind('<Button-3>', self.context_menu)
        # Tk's default Ctrl bindings depend on the active keyboard layout on Windows.
        for widget in (self.input, self.output):
            widget.bind('<Control-KeyPress>', self.clipboard_shortcut)
        self.status = tk.StringVar(value='Введите текст — перевод появится автоматически')
        tk.Label(self.page, textvariable=self.status, bg=BG, fg=MUTED, anchor='w').grid(row=4, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        self.requests = queue.Queue(maxsize=1); self.results = queue.SimpleQueue()
        self.generation = 0; self.debounce = None; self.closed = False; self.cache = {}
        self.identifier = None
        self.job = self.page.after(100, self.poll)
        self.worker_thread = threading.Thread(target=self.worker, daemon=True)
        self.worker_thread.start()

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
        if action == '<<Copy>>':
            if widget.tag_ranges('sel'):
                text = widget.get('sel.first', 'sel.last')
                widget.clipboard_clear()
                widget.clipboard_append(text)
            return
        widget.event_generate(action)

    def clipboard_shortcut(self, event):
        # Windows reports virtual key codes for the physical C, V, X and Z keys,
        # including when the Russian or German keyboard layout is active.
        if event.state & 0x0008:  # Do not intercept AltGr / Ctrl+Alt.
            return None
        action = {67: '<<Copy>>', 86: '<<Paste>>', 88: '<<Cut>>', 90: '<<Undo>>'}.get(event.keycode)
        if action is None or (event.widget is self.output and action != '<<Copy>>'):
            return None
        self.clipboard_action(event.widget, action)
        return 'break'

    def modified(self, event=None):
        if self.input.edit_modified():
            self.input.edit_modified(False); self.changed()

    def direction_selected(self, event=None):
        self.direction_mode = DIRECTIONS[self.direction.get()]
        self.changed()

    def changed(self, event=None):
        self.generation += 1
        if self.debounce is not None: self.page.after_cancel(self.debounce); self.debounce = None
        text = self.input.get('1.0','end-1c').strip()
        self.set_output('')
        if self.direction_mode == 'auto':
            self.direction.set(AUTO_LABEL)
        if not text:
            self.status.set('Введите текст — перевод появится автоматически'); return
        self.status.set('Ожидаем завершения ввода…')
        self.debounce = self.page.after(400, self.submit)

    def submit(self):
        if self.debounce is not None: self.page.after_cancel(self.debounce)
        self.debounce = None
        self.direction_mode = DIRECTIONS.get(self.direction.get(), self.direction_mode)
        item = (self.generation, self.input.get('1.0','end-1c').strip(), self.direction_mode)
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
                uncertain = False
                if source == 'auto':
                    if self.identifier is None:
                        from langid.langid import LanguageIdentifier, model
                        self.identifier = LanguageIdentifier.from_modelstring(model, norm_probs=True)
                        self.identifier.set_languages(['en', 'de'])
                    source, uncertain = detect_text_language(text, self.identifier)
                    if source is None:
                        self.results.put((generation, False, 'Не удалось определить язык. Введите более длинный текст на одном языке.'))
                        continue
                    self.results.put((generation, 'detected', source))
                if source == 'ru_de':
                    if not (DATA / 'translate-en_de-1_3').is_dir():
                        raise FileNotFoundError('Модель для перевода на немецкий не установлена. Выберите немецкий компонент в установщике.')
                    if 'ru' not in self.cache: self.cache['ru'] = Language('ru', load_speech=False)
                    if 'ru_de' not in self.cache: self.cache['ru_de'] = EnglishToGerman(self.cache['ru'])
                elif source == 'de':
                    if not (DATA / 'translate-de_en-1_9').is_dir():
                        raise FileNotFoundError('Немецкая модель не установлена. Выберите её в установщике.')
                    if 'en' not in self.cache: self.cache['en'] = Language('en', load_speech=False)
                    if 'de' not in self.cache: self.cache['de'] = GermanTranslation(self.cache['en'])
                elif source not in self.cache:
                    self.cache[source] = Language(source, load_speech=False)
                result = self.cache[source].translate(prepare_translation_text(text, source))
                message = LANGUAGE_LABELS[source] + (' · язык определён предположительно' if uncertain else '')
                self.results.put((generation, True, (result, message)))
            except Exception as exc:
                self.results.put((generation, False, str(exc) if isinstance(exc, FileNotFoundError) else 'Не удалось загрузить модель перевода. Проверьте установку приложения.'))

    def set_output(self, text):
        self.output.configure(state='normal'); self.output.delete('1.0','end'); self.output.insert('1.0',text); self.output.configure(state='disabled')

    def poll(self):
        while not self.results.empty():
            generation, ok, result = self.results.get()
            if generation != self.generation: continue
            if ok == 'detected':
                if self.direction_mode == 'auto': self.direction.set(LANGUAGE_LABELS[result])
                continue
            if ok: self.set_output(result[0]); self.status.set('Перевод готов · ' + result[1])
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
        self.worker_thread.join(timeout=2)
