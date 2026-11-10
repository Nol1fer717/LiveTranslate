import queue
import os
import threading
import time
import wave
import tkinter as tk
from clipboard_shortcuts import bind_shortcuts
import diagnostics
from transcript_actions import add_copy_button
import theme_manager
from model_readiness import base_models_ready as check_base_models_ready, recover_stale_marker
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pyaudiowpatch as pa
from vosk import SpkModel

from engine import DATA, GermanTranslation, Language, SPEAKER_PATH, SourceStop, capture, devices
from whisper_stream import load_whisper, UnrecognizedAudioError, StuckRecognizerError
from storage import Storage
from library_ui import LibraryUI
from translator_ui import TranslatorUI
from user_data import data_directory
from rounded_button import RoundedButton
from settings import read_split_level, save_split_level, read_preferences, save_preferences

SOURCES = ("Микрофон", "Звук компьютера")
DIRECTIONS = ("Автоопределение", "Русский → Английский", "Английский → Русский")
MODES = ("Микрофон", "Звук компьютера", "Микрофон + компьютер")
VIEWS = ("Оба", "Транскрипция", "Перевод")
THEMES = {'system': 'Системная', 'light': 'Светлая', 'dark': 'Тёмная'}


def base_models_ready():
    return check_base_models_ready(DATA)


class App:
    def __init__(self, root):
        self.root = root
        self.palette = dict(theme_manager.LIGHT)
        root._livetranslate_palette = self.palette
        try:
            diagnostics.configure(root)
        except OSError:
            pass
        root.report_callback_exception = self.report_ui_exception
        root.title("LiveTranslate")
        root.geometry("980x760")
        root.minsize(760, 600)
        root.configure(bg=self.palette['BG'])
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Dark.TCombobox", fieldbackground=self.palette['FIELD'], background=self.palette['FIELD'],
                        foreground=self.palette['TEXT'], arrowcolor=self.palette['MUTED'], bordercolor=self.palette['BORDER'], lightcolor=self.palette['BORDER'], darkcolor=self.palette['BORDER'], padding=8)
        style.map("Dark.TCombobox", fieldbackground=[("readonly", self.palette['FIELD'])],
                  foreground=[("readonly", self.palette['TEXT'])])
        style.configure("Vertical.TScrollbar", background=self.palette['BORDER'], troughcolor=self.palette['CARD'], bordercolor=self.palette['CARD'],
                        arrowcolor=self.palette['MUTED'])

        masthead = tk.Frame(root, bg=self.palette['CARD'], padx=28, pady=14, highlightbackground=self.palette['BORDER'], highlightthickness=1)
        masthead.grid(row=0, column=0, sticky="ew")
        tk.Label(masthead, text="LiveTranslate", bg=self.palette['CARD'], fg=self.palette['TEXT'], font=("Segoe UI", 17, "bold")).pack(side="left")
        tk.Label(masthead, text="Перевод и изучение языков", bg=self.palette['CARD'], fg=self.palette['MUTED'], font=("Segoe UI", 10)).pack(side="left", padx=(16, 0))
        style.configure("Modern.TNotebook", background=self.palette['BG'], borderwidth=0)
        style.layout("Modern.TNotebook.Tab", [])
        navigation = tk.Frame(root, bg=self.palette['BG'], padx=24, pady=8)
        navigation.grid(row=1, column=0, sticky="ew")
        tabs = ttk.Notebook(root, style="Modern.TNotebook")
        tabs.grid(row=2, column=0, sticky="nsew")
        self.tabs = tabs
        self.settings_path = data_directory() / 'settings.json'
        self.preferences = read_preferences(self.settings_path)
        self.settings_page = tk.Frame(tabs, bg=self.palette['BG'], padx=28, pady=20)
        settings_canvas = tk.Canvas(self.settings_page, bg=self.palette['BG'], highlightthickness=0)
        settings_scroll = ttk.Scrollbar(self.settings_page, orient='vertical', command=settings_canvas.yview, style='Vertical.TScrollbar')
        settings_scroll.pack(side='right', fill='y')
        settings_canvas.pack(side='left', fill='both', expand=True)
        settings_canvas.configure(yscrollcommand=settings_scroll.set)
        settings_content = tk.Frame(settings_canvas, bg=self.palette['BG'])
        settings_window = settings_canvas.create_window((0, 0), window=settings_content, anchor='nw')
        settings_content.bind('<Configure>', lambda event: settings_canvas.configure(scrollregion=settings_canvas.bbox('all')))
        settings_canvas.bind('<Configure>', lambda event: settings_canvas.itemconfigure(settings_window, width=event.width))
        def settings_wheel(event):
            if event.delta and tabs.select() == str(self.settings_page) and str(event.widget).startswith(str(self.settings_page)):
                if not isinstance(event.widget, (ttk.Combobox, tk.Scale, tk.Entry, tk.Text)):
                    settings_canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
                    return 'break'
        root.bind_all('<MouseWheel>', settings_wheel, add='+')
        tk.Label(settings_content, text='Настройки', bg=self.palette['BG'], fg=self.palette['TEXT'], font=('Segoe UI', 19, 'bold')).pack(anchor='w')
        device_card = tk.Frame(settings_content, bg=self.palette['CARD'], padx=18, pady=16, highlightthickness=1, highlightbackground=self.palette['BORDER'])
        device_card.pack(fill='x', pady=(18, 0))
        device_card.columnconfigure(0, weight=1)
        page = tk.Frame(tabs, bg=self.palette['BG'], padx=28, pady=20)
        tabs.add(page, text="Перевод")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(4, weight=1)

        header = tk.Frame(page, bg=self.palette['BG'])
        header.grid(row=0, sticky="ew", pady=(0, 20))
        tk.Label(header, text="Перевод", bg=self.palette['BG'], fg=self.palette['TEXT'],
                 font=("Segoe UI", 19, "bold")).pack(side="left")
        self.status = tk.StringVar(value="Выберите источник и начните перевод")
        tk.Label(header, textvariable=self.status, bg=self.palette['BG'], fg=self.palette['MUTED'],
                 font=("Segoe UI", 10), anchor="e").pack(side="right", fill="x", expand=True, padx=(18, 0))

        controls = tk.Frame(page, bg=self.palette['CARD'], padx=18, pady=16, highlightthickness=1,
                            highlightbackground=self.palette['BORDER'])
        controls.grid(row=1, sticky="ew", pady=(0, 18))
        controls.columnconfigure(0, weight=1)

        top = tk.Frame(controls, bg=self.palette['CARD'])
        top.grid(row=0, sticky="ew")
        tk.Label(top, text="Язык", bg=self.palette['CARD'], fg=self.palette['MUTED'], font=("Segoe UI", 10)).pack(side="left", padx=(0, 10))
        self.direction = ttk.Combobox(top, values=DIRECTIONS, state="readonly", width=25, style="Dark.TCombobox")
        saved_direction = self.preferences.get('speech_direction', DIRECTIONS[0])
        self.direction.set(saved_direction if saved_direction in DIRECTIONS else DIRECTIONS[0])
        self.direction.pack(side="left")
        self.direction.bind('<<ComboboxSelected>>', self.save_device_settings)
        self.start = RoundedButton(top, text="Начать перевод", command=self.toggle, bg=self.palette['ACCENT'], fg=self.palette['ON_ACCENT'],
                               activebackground=self.palette['ACCENT_DARK'], activeforeground=self.palette['ON_ACCENT'], relief="flat",
                               padx=20, pady=8, cursor="hand2", font=("Segoe UI", 10, "bold"))
        self.start._accent_action = True
        self.start.pack(side="right")
        self.recover_button = RoundedButton(top, text='Сохранить фрагмент', command=self.save_unrecognized,
                                            bg=self.palette['FIELD'], fg=self.palette['TEXT'], state='disabled', padx=12, pady=8)
        RoundedButton(top, text='Настроить звук', command=lambda: tabs.select(self.settings_page),
                      bg=self.palette['CARD'], fg=self.palette['ACCENT'], activebackground=self.palette['FIELD'], activeforeground=self.palette['ACCENT'],
                      padx=12, pady=8).pack(side='right', padx=(0, 8))

        saved_mode = self.preferences.get('source_mode', MODES[2])
        self.mode = tk.StringVar(value=saved_mode if saved_mode in MODES else MODES[2])
        self.mode_buttons = []
        mode_bar = tk.Frame(controls, bg=self.palette['CARD'])
        mode_bar.grid(row=1, sticky="ew", pady=(14, 0))
        for label in MODES:
            button = RoundedButton(mode_bar, text=label, command=lambda value=label: self.set_mode(value),
                               relief="flat", padx=14, pady=7, cursor="hand2", font=("Segoe UI", 10, "bold"))
            button.pack(side="left", padx=(0, 6))
            self.mode_buttons.append(button)

        choices = tk.Frame(device_card, bg=self.palette['CARD'])
        choices.grid(row=2, sticky="ew", pady=(8, 0))
        choices.columnconfigure((0, 1), weight=1, uniform="device")
        self.device_boxes = []
        for index, title in enumerate(SOURCES):
            group = tk.Frame(choices, bg=self.palette['CARD'])
            group.grid(row=0, column=index, sticky="ew", padx=(0, 8) if index == 0 else (8, 0))
            group.columnconfigure(0, weight=1)
            tk.Label(group, text=title, bg=self.palette['CARD'], fg=self.palette['MUTED'], font=("Segoe UI", 9)).grid(sticky="w", pady=(0, 4))
            box = ttk.Combobox(group, state="readonly", style="Dark.TCombobox", width=18)
            box.grid(row=1, column=0, sticky="ew")
            box.bind('<<ComboboxSelected>>', self.save_device_settings)
            self.device_boxes.append(box)

        options = tk.Frame(device_card, bg=self.palette['CARD'])
        options.grid(row=3, sticky="ew", pady=(10, 0))
        saved_identify = self.preferences.get('identify_speakers', SPEAKER_PATH.is_dir())
        self.identify = tk.BooleanVar(value=bool(SPEAKER_PATH.is_dir() and saved_identify is True))
        self.speaker_check = tk.Checkbutton(options,
                                            text="Различать голоса" if SPEAKER_PATH.is_dir() else "Различение голосов не установлено",
                                            variable=self.identify, command=self.save_device_settings,
                                            bg=self.palette['CARD'], fg=self.palette['TEXT'], selectcolor=self.palette['FIELD'], activebackground=self.palette['CARD'],
                                            activeforeground=self.palette['TEXT'], highlightthickness=0)
        self.speaker_check.pack(side="left")
        saved_wav = self.preferences.get('save_wav', False)
        self.save = tk.BooleanVar(value=saved_wav if isinstance(saved_wav, bool) else False)
        self.check = tk.Checkbutton(options, text="Сохранять звук в WAV", variable=self.save, command=self.save_device_settings,
                                    bg=self.palette['CARD'], fg=self.palette['TEXT'], selectcolor=self.palette['FIELD'], activebackground=self.palette['CARD'],
                                    activeforeground=self.palette['TEXT'], highlightthickness=0)
        self.check.pack(side="left", padx=(18, 0))
        self.refresh = RoundedButton(options, text="Обновить устройства", command=self.scan, bg=self.palette['CARD'], fg=self.palette['ACCENT'],
                                 activebackground=self.palette['FIELD'], activeforeground=self.palette['TEXT'], relief="flat", cursor="hand2")
        self.refresh.pack(side="right")
        saved_quiet = self.preferences.get('quiet_voice', False)
        self.quiet_voice = tk.BooleanVar(value=saved_quiet if isinstance(saved_quiet, bool) else False)
        self.quiet_check = tk.Checkbutton(device_card, text='Тихий голос · авто Whisper (экспериментально)',
                                          variable=self.quiet_voice, command=self.save_device_settings,
                                          bg=self.palette['CARD'], fg=self.palette['TEXT'], selectcolor=self.palette['FIELD'], activebackground=self.palette['CARD'],
                                          activeforeground=self.palette['TEXT'], highlightthickness=0)
        self.quiet_check.grid(row=4, sticky='w', pady=(8, 0))

        view_bar = tk.Frame(page, bg=self.palette['BG'])
        view_bar.grid(row=2, sticky="ew", pady=(0, 10))
        self.view = tk.StringVar(value=VIEWS[0])
        self.view_buttons = []
        for label in VIEWS:
            button = RoundedButton(view_bar, text=label, command=lambda value=label: self.set_view(value),
                               relief="flat", padx=16, pady=7, cursor="hand2", font=("Segoe UI", 10, "bold"))
            button.pack(side="left", padx=(0, 4))
            self.view_buttons.append(button)

        results = tk.Frame(page, bg=self.palette['CARD'], highlightthickness=1, highlightbackground=self.palette['BORDER'])
        results.grid(row=4, sticky="nsew")
        results.rowconfigure(0, weight=1)
        results.columnconfigure(0, weight=1)
        self.history = tk.Text(results, wrap="word", bg=self.palette['CARD'], fg=self.palette['TEXT'], insertbackground=self.palette['TEXT'],
                               selectbackground=self.palette['SELECTION'], selectforeground=self.palette['TEXT'], relief="flat", padx=20, pady=18,
                               font=("Segoe UI", 12), state="disabled", cursor="arrow")
        self.history.grid(row=0, column=0, sticky="nsew")
        bind_shortcuts(self.history)
        scrollbar = ttk.Scrollbar(results, orient="vertical", command=self.history.yview, style="Vertical.TScrollbar")
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=8)
        self._history_at_bottom = True
        def on_history_scroll(first, last):
            scrollbar.set(first, last)
            self._history_at_bottom = float(last) >= 0.999
        self.history.configure(yscrollcommand=on_history_scroll)
        self.history.bind('<Configure>', self.history_resized, add='+')
        self.history.tag_configure("meta", foreground=self.palette['MUTED'], font=("Segoe UI", 9), spacing1=12, spacing3=6)
        self.history.tag_configure("source_label", foreground=self.palette['ACCENT'], font=("Segoe UI", 10, "bold"))
        self.history.tag_configure("target_label", foreground=self.palette['ACCENT_DARK'], font=("Segoe UI", 10, "bold"))
        self.history.tag_configure("source", foreground=self.palette['MUTED'], font=("Segoe UI", 12), spacing3=6)
        self.history.tag_configure("target", foreground=self.palette['TEXT'], font=("Segoe UI", 13), spacing3=12)
        self.history.tag_configure("target_label", justify="left")
        self.history.tag_configure("target", justify="left")
        self.history.tag_configure("placeholder", foreground=self.palette['MUTED'], font=("Segoe UI", 11))

        self.storage = Storage()
        if self.storage.migration_warnings:
            messagebox.showwarning('Перенос данных', 'Не удалось перенести некоторые старые аудиозаписи. Оригиналы сохранены; проверьте доступ к ним и перезапустите приложение для повторной попытки.', parent=root)
        if self.storage.legacy_conflict:
            messagebox.showwarning("История и заметки", "В «Документах» уже есть своя база. Она сохранена без изменений; старая база в AppData тоже сохранена, но автоматически с ней не объединена.", parent=root)
        self.translator = TranslatorUI(tabs)
        self.library = LibraryUI(tabs, self.storage)
        self.split_level = tk.IntVar(value=read_split_level(self.settings_path))
        tabs.add(self.settings_page, text='Настройки')
        card = tk.Frame(settings_content, bg=self.palette['CARD'], padx=20, pady=18, highlightthickness=1, highlightbackground=self.palette['BORDER'])
        card.pack(fill='x', pady=(18, 0))
        theme_line = tk.Frame(card, bg=self.palette['CARD'])
        theme_line.pack(fill='x', pady=(0, 12))
        tk.Label(theme_line, text='Тема', bg=self.palette['CARD'], fg=self.palette['TEXT']).pack(side='left', padx=(0, 8))
        self.theme_choice = ttk.Combobox(theme_line, state='readonly', values=('Системная', 'Светлая', 'Тёмная'), style='Dark.TCombobox')
        saved_theme = self.preferences.get('theme', 'system')
        self.theme_choice.set(THEMES.get(saved_theme, saved_theme if saved_theme in THEMES.values() else THEMES['system']))
        self.theme_choice.pack(side='left')
        self.theme_choice.bind('<<ComboboxSelected>>', self.change_theme)
        tk.Label(card, text='Скорость разбиения высказываний', bg=self.palette['CARD'], fg=self.palette['TEXT'], font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        tk.Label(card, text='1 — чаще, 10 — реже. Изменение применяется при следующем запуске перевода.', bg=self.palette['CARD'], fg=self.palette['MUTED'], wraplength=750, justify='left').pack(anchor='w', pady=(6, 8))
        scale = tk.Scale(card, from_=1, to=10, orient='horizontal', resolution=1, variable=self.split_level,
                         bg=self.palette['CARD'], fg=self.palette['TEXT'], activebackground=self.palette['ACCENT'], highlightthickness=0, troughcolor=self.palette['ACCENT_SOFT'],
                         length=430, showvalue=True)
        scale.pack(anchor='w', fill='x')
        scale.bind('<ButtonRelease-1>', self.save_settings)
        scale.bind('<KeyRelease>', self.save_settings)
        tk.Label(card, text='Речь и перевод показываются предварительно; после завершения фрагмента появляется окончательный перевод.', bg=self.palette['CARD'], fg=self.palette['MUTED'], wraplength=750, justify='left').pack(anchor='w', pady=(10, 0))
        log_controls = tk.Frame(settings_content, bg=self.palette['BG'])
        log_controls.pack(fill='x', pady=(14, 0))
        RoundedButton(log_controls, text='Открыть папку журналов', command=self.open_logs,
                      bg=self.palette['FIELD'], fg=self.palette['TEXT']).pack(side='left', padx=(0, 8))
        RoundedButton(log_controls, text='Скопировать диагностику', command=self.copy_diagnostics,
                      bg=self.palette['FIELD'], fg=self.palette['TEXT']).pack(side='left')
        tk.Label(log_controls, text='Журнал', bg=self.palette['BG'], fg=self.palette['MUTED']).pack(side='left', padx=(18, 6))
        self.log_level = ttk.Combobox(log_controls, state='readonly', values=('Обычный', 'Подробный'), width=12, style='Dark.TCombobox')
        self.log_level.set(self.preferences.get('log_level', 'Обычный') if self.preferences.get('log_level') in ('Обычный', 'Подробный') else 'Обычный')
        self.log_level.pack(side='left')
        self.log_level.bind('<<ComboboxSelected>>', self.change_log_level)
        diagnostics.set_level(self.log_level.get() == 'Подробный')
        nav_buttons = []
        for label, target in (("Перевод", page), ("Переводчик", self.translator.page), ("История", self.library.history_page), ("Заметки", self.library.notes_page), ("Настройки", self.settings_page)):
            control = RoundedButton(navigation, text=label, command=lambda selected=target: tabs.select(selected),
                                relief="flat", padx=18, pady=7, cursor="hand2", font=("Segoe UI", 10, "bold"),
                                activebackground=self.palette['HOVER'], activeforeground=self.palette['ACCENT'])
            control.pack(side="left", padx=(0, 6))
            nav_buttons.append((control, target))

        def update_navigation(event=None):
            current = tabs.select()
            for control, target in nav_buttons:
                active = current == str(target)
                control.configure(bg=self.palette['ACCENT_SOFT'] if active else self.palette['BG'], fg=self.palette['ACCENT'] if active else self.palette['MUTED'])
            if current == str(self.library.history_page):
                self.library.refresh_history()

        tabs.bind("<<NotebookTabChanged>>", update_navigation)
        update_navigation()
        self.session_id = None
        self.library.active_session = lambda: self.session_id
        self.events = queue.SimpleQueue()
        self.entries = []
        self.previews = {}
        self.partials = {}
        self.preview_positions = {}
        self.preview_sequence = 0
        self.unrecognized_audio = []
        self.stop = None
        self.restart_required = False
        self.stop_timeout_job = None
        self.closing = False
        self.cache = {}
        self.speaker_model = None
        self.speaker_diarizer = None
        self.whisper = None
        self.device_items = [[], []]
        self.scan()
        self.set_mode(self.mode.get())
        self.set_view(self.view.get())
        self.models_ready = base_models_ready()
        self.last_model_check = 0.0
        self.model_recovery_running = False
        self.model_recovery_next = 0.0
        self.model_recovery_failed = None
        if not self.models_ready:
            self.status.set('Загрузка моделей выполняется в фоне')
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_job = None
        self.current_palette = theme_manager.LIGHT
        self.change_theme(save=False)
        self.theme_job = self.root.after(1500, self.poll_theme)
        self.poll()
        if diagnostics.consume_crash_notice():
            self.status.set('При предыдущем запуске произошла ошибка. Журнал доступен в настройках.')

    def change_theme(self, event=None, save=True):
        choice = self.theme_choice.get()
        desired = theme_manager.system_theme() if choice == 'Системная' else ('dark' if choice == 'Тёмная' else 'light')
        palette = theme_manager.DARK if desired == 'dark' else theme_manager.LIGHT
        if palette is not self.current_palette:
            theme_manager.apply_palette(self.root, self.current_palette, palette)
            self.current_palette = palette
        if save:
            key = next((key for key, label in THEMES.items() if label == choice), 'system')
            self.persist_preferences({'theme': key}, 'Не удалось сохранить тему')

    def persist_preferences(self, updates, failure_message):
        try:
            save_preferences(self.settings_path, updates)
            self.preferences.update(updates)
        except (OSError, ValueError, tk.TclError) as exc:
            self.status.set(f'{failure_message}: {exc}')

    def poll_theme(self):
        if self.theme_choice.get() == 'Системная':
            self.change_theme(save=False)
        self.theme_job = self.root.after(1500, self.poll_theme)

    def set_mode(self, mode):
        changed = self.mode.get() != mode
        self.mode.set(mode)
        for button, label in zip(self.mode_buttons, MODES):
            selected = label == mode
            button.configure(bg=self.palette['ACCENT_SOFT'] if selected else self.palette['CARD'], fg=self.palette['ACCENT'] if selected else self.palette['TEXT'],
                             activebackground=self.palette['HOVER'], activeforeground=self.palette['TEXT'])
        self.update_devices()
        if changed and hasattr(self, 'device_items'):
            self.save_device_settings()

    def save_device_settings(self, event=None):
        prior = self.preferences.get('devices', [])
        names = [box.get() or (prior[i] if isinstance(prior, list) and i < len(prior) else '')
                 for i, box in enumerate(self.device_boxes)]
        updates = {'source_mode': self.mode.get(), 'speech_direction': self.direction.get(), 'devices': names,
                   'identify_speakers': bool(self.identify.get()), 'save_wav': bool(self.save.get()),
                   'quiet_voice': bool(self.quiet_voice.get())}
        self.persist_preferences(updates, 'Не удалось сохранить настройки')

    def save_settings(self, event=None):
        try:
            save_split_level(self.settings_path, self.split_level.get())
        except (OSError, ValueError, tk.TclError) as exc:
            messagebox.showerror('Настройки', f'Не удалось сохранить настройки: {exc}', parent=self.root)

    def open_logs(self):
        try:
            directory = diagnostics.log_directory()
            directory.mkdir(parents=True, exist_ok=True)
            os.startfile(directory)
        except OSError as exc:
            self.status.set(f'Не удалось открыть папку журналов: {exc}')

    def report_ui_exception(self, kind, value, tb):
        diagnostics.log_error('tk', kind, tb)
        dialog = tk.Toplevel(self.root)
        dialog.title('Ошибка LiveTranslate')
        dialog.transient(self.root)
        dialog.configure(bg=self.palette['BG'])
        content = tk.Frame(dialog, bg=self.palette['BG'], padx=20, pady=18); content.pack(fill='both', expand=True)
        tk.Label(content, text='Произошла ошибка интерфейса.', bg=self.palette['BG'], fg=self.palette['TEXT'],
                 font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        tk.Label(content, text='Подробности сохранены в локальном журнале. Текст разговора в него не записывается.',
                 bg=self.palette['BG'], fg=self.palette['MUTED'], wraplength=480, justify='left').pack(anchor='w', pady=(8, 12))
        actions = tk.Frame(content, bg=self.palette['BG']); actions.pack(fill='x')
        RoundedButton(actions, text='Открыть журнал', command=self.open_logs, bg=self.palette['FIELD'], fg=self.palette['TEXT']).pack(side='left', padx=(0, 8))
        RoundedButton(actions, text='Скопировать диагностику', command=self.copy_diagnostics, bg=self.palette['FIELD'], fg=self.palette['TEXT']).pack(side='left', padx=(0, 8))
        RoundedButton(actions, text='Закрыть', command=dialog.destroy, bg=self.palette['FIELD'], fg=self.palette['TEXT']).pack(side='right')

    def copy_diagnostics(self):
        try:
            path = diagnostics.log_directory() / 'application.log'
            content = path.read_text(encoding='utf-8')[-16000:]
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.status.set('Диагностика скопирована')
        except OSError:
            self.status.set('Журнал диагностики пока недоступен')

    def change_log_level(self, event=None):
        choice = self.log_level.get()
        diagnostics.set_level(choice == 'Подробный')
        self.persist_preferences({'log_level': choice}, 'Не удалось сохранить уровень журнала')

    def update_devices(self):
        active = (self.mode.get() != MODES[1], self.mode.get() != MODES[0])
        for index, box in enumerate(self.device_boxes):
            box.configure(state="readonly" if active[index] and self.stop is None else "disabled")
        self.speaker_check.configure(state="normal" if active[1] and self.stop is None and SPEAKER_PATH.is_dir() else "disabled")

    def set_view(self, view):
        self.view.set(view)
        for button, label in zip(self.view_buttons, VIEWS):
            button.configure(bg=self.palette['ACCENT_SOFT'] if label == view else self.palette['BG'],
                             fg=self.palette['ACCENT'] if label == view else self.palette['MUTED'],
                             activebackground=self.palette['HOVER'], activeforeground=self.palette['TEXT'])
        self.render()
        self.render_preview()

    def scan(self):
        try:
            self.device_items = list(devices())
            ambiguous = False
            for index, (box, items) in enumerate(zip(self.device_boxes, self.device_items)):
                box.configure(values=[d["name"] for d in items])
                if items:
                    saved = self.preferences.get('devices', [])
                    name = saved[index] if isinstance(saved, list) and index < len(saved) else None
                    matches = [i for i, device in enumerate(items) if device['name'] == name]
                    position = matches[0] if len(matches) == 1 else None
                    if name and position is None:
                        box.set('')
                        ambiguous = True
                    else:
                        box.current(position if position is not None else 0)
            self.status.set('Устройство недоступно или имена совпадают. Выберите его в настройках.' if ambiguous else "Выберите источник и начните перевод")
            self.update_devices()
        except Exception as exc:
            self.status.set(f"Не удалось получить устройства: {exc}")

    def render(self):
        selected = self.history.tag_ranges("sel")
        selected_text = self.history.get("sel.first", "sel.last") if selected else None
        at_bottom = self.history.yview()[1] >= 0.999
        anchor = self.history.index('@0,0') if not at_bottom else None
        self.history.configure(state="normal")
        old_count = getattr(self, '_rendered_count', None)
        interleaved = any(pos < len(self.entries) and (self.previews.get(i) or self.partials.get(i))
                          for i, (pos, _) in self.preview_positions.items())
        incremental = (not interleaved and not getattr(self, '_rendered_interleaved', False)
                       and old_count is not None and old_count <= len(self.entries)
                       and getattr(self, '_rendered_view', None) == self.view.get()
                       and not getattr(self, '_rendered_placeholder', True))
        if incremental:
            self.history.delete('preview_start', 'end')
            new_entries = self.entries[old_count:]
            placeholder = False
        else:
            for child in self.history.winfo_children():
                child.destroy()
            self.history.delete("1.0", "end")
            placeholder = not self.entries and not any(self.previews.values()) and not any(self.partials.values())
            if placeholder:
                self.history.insert("end", "Здесь появятся распознанная речь и перевод.", "placeholder")
            new_entries = self.entries
        if interleaved:
            pending = sorted(((pos, sequence, i) for i, (pos, sequence) in self.preview_positions.items()
                              if self.previews.get(i) or self.partials.get(i)))
            combined = []
            for position in range(len(self.entries) + 1):
                combined.extend({'preview_index': i} for pos, _, i in pending if pos == position)
                if position < len(self.entries): combined.append(self.entries[position])
            new_entries = combined
        for entry in new_entries:
            if 'preview_index' in entry:
                self.render_source_preview(entry['preview_index'])
                continue
            if entry.get("session"):
                self.history.insert("end", entry["session"] + "\n", "meta")
                continue
            meta = " · ".join(x for x in (entry["time"], SOURCES[entry["index"]], entry["speaker"]) if x)
            self.history.insert("end", meta + "\n", "meta")
            if self.view.get() != VIEWS[2]:
                self.history.insert("end", f'[{entry["from"]}]  ', "source_label")
                self.history.insert("end", entry["source"] + "\n", "source")
            if self.view.get() != VIEWS[1]:
                self.history.insert("end", f'[{entry["to"]}]  ', "target_label")
                self.history.insert("end", entry["target"] + "\n", "target")
                add_copy_button(self.history, entry['target'], self.copy_feedback)
        self.history.mark_set('preview_start', 'end-1c')
        self.history.mark_gravity('preview_start', 'left')
        self._rendered_count = len(self.entries)
        self._rendered_interleaved = interleaved
        self._rendered_view = self.view.get()
        self._rendered_placeholder = placeholder
        if not interleaved:
            for index in dict.fromkeys((*self.previews, *self.partials)):
                self.render_source_preview(index)
        if selected_text:
            match = self.history.search(selected_text, "1.0", stopindex="end", exact=True)
            if match:
                self.history.tag_add("sel", match, f"{match}+{len(selected_text)}c")
        if anchor is not None:
            self.history.yview(anchor)
        elif at_bottom:
            self.history.see("end")
        self.history.configure(state="disabled")

    def render_source_preview(self, index):
        value = self.previews.get(index)
        if value:
            source, target, *language = value
            source_lang = language[0] if language else "…"
            translating = bool(len(language) > 1 and language[1])
            target_lang = "EN" if source_lang == "RU" else "RU"
            self.history.insert("end", f"{SOURCES[index]} · Предварительно\n", "meta")
            if self.view.get() != VIEWS[2]:
                self.history.insert("end", f"[{source_lang}]  ", "source_label")
                self.history.insert("end", source + "\n", "source")
            if self.view.get() != VIEWS[1]:
                self.history.insert("end", f"[{target_lang}]  ", "target_label")
                self.history.insert("end", ((target + '  ·  Переводим…') if target and translating else (target or 'Переводим…')) + "\n", "target")
        elif self.view.get() != VIEWS[2] and self.partials.get(index):
            self.history.insert("end", f"{SOURCES[index]} · Распознавание\n", "meta")
            self.history.insert("end", self.partials[index] + "\n", "source")

    def render_preview(self):
        self.render()

    def history_resized(self, event=None):
        if event is not None:
            margin = max(0, int(event.width * .3))
            for tag in ('source', 'source_label'):
                self.history.tag_configure(tag, rmargin=margin)
            for tag in ('target', 'target_label'):
                self.history.tag_configure(tag, lmargin1=margin, lmargin2=margin, justify='left')
        if self._history_at_bottom:
            self.root.after_idle(lambda: self.history.see('end') if self.history.winfo_exists() else None)

    def copy_feedback(self, message):
        previous = self.status.get()
        self.status.set(message)
        self.root.after(2000, lambda: self.status.set(previous) if self.status.get() == message else None)

    def toggle(self):
        if self.stop is not None:
            self.stop.set()
            self.start.configure(state="disabled")
            self.status.set("Завершаем обработку…")
            self.schedule_stop_warning()
            return
        if not base_models_ready():
            message = ('Подготовка была прервана или файлы повреждены. Повторно запустите установщик.' if self.model_recovery_failed is not None else
                       'Модели ещё загружаются или проверяются. Дождитесь окончания подготовки. Если загрузка не завершилась, запустите установщик повторно.')
            messagebox.showinfo('Подготовка моделей', message)
            return
        indices = ((0,), (1,), (0, 1))[MODES.index(self.mode.get())]
        selected = []
        for index in indices:
            position = self.device_boxes[index].current()
            if position < 0:
                messagebox.showerror("Устройство", f"Не найдено устройство: {SOURCES[index]}. Выберите устройство во вкладке «Настройки».")
                self.tabs.select(self.settings_page)
                return
            selected.append((index, self.device_items[index][position],
                             ("auto", "ru", "en")[self.direction.current()]))
        folder = None
        if self.save.get():
            folder = data_directory() / "Recordings" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            try:
                folder.mkdir(parents=True)
            except OSError as exc:
                messagebox.showerror("Запись", str(exc))
                return
        try:
            self.session_id = self.storage.start_session(self.mode.get())
        except Exception as exc:
            messagebox.showerror("История", f"Не удалось начать сохранение сеанса: {exc}")
            return
        if self.entries:
            self.entries.append({"session": "Новый сеанс · " + datetime.now().strftime("%H:%M")})
            self.render()
        self.folder = folder
        self.stop = threading.Event()
        self.failure = ""
        self.active_count = len(selected)
        self.ready = 0
        self.direction.configure(state="disabled")
        self.refresh.configure(state="disabled")
        self.check.configure(state="disabled")
        self.quiet_check.configure(state="disabled")
        for button in self.mode_buttons:
            button.configure(state="disabled")
        self.update_devices()
        self.start.configure(text="Остановить", state='disabled')
        current_stop = self.stop
        def enable_stop():
            if self.stop is current_stop and not current_stop.is_set():
                self.start.configure(state='normal')
        self.root.after(500, enable_stop)
        self.status.set("Подготавливаем модели и устройства…")
        detect = self.identify.get() and any(index == 1 for index, _, _ in selected)
        self.current_split_level = self.split_level.get()
        self.current_quiet_voice = self.quiet_voice.get()
        self.current_auto = any(lang == 'auto' for _, _, lang in selected)
        threading.Thread(target=self.session, args=(selected, folder, self.stop, detect), daemon=True).start()

    def session(self, selected, folder, stop, detect):
        def emit(kind, index, value):
            self.events.put((kind, index, value))

        def run(audio, index, lang, device):
            try:
                path = folder / ("microphone.wav", "computer.wav")[index] if folder else None
                speaker_model = self.speaker_model if index == 1 and detect else None
                diarizer = self.speaker_diarizer if index == 1 and detect and lang == 'auto' else None
                capture(audio, device, self.cache if lang == "auto" else self.cache[lang],
                        index, SourceStop(stop), emit, path, speaker_model, self.whisper if lang == "auto" else None,
                        diarizer=diarizer, split_level=self.current_split_level, quiet_mode=self.current_quiet_voice)
            except Exception as exc:
                diagnostics.log_error('capture', type(exc), exc.__traceback__)
                if isinstance(exc, StuckRecognizerError) or getattr(exc, 'restart_required', False):
                    emit('restart_required', index, None)
                if isinstance(exc, UnrecognizedAudioError):
                    emit('unrecognized_audio', index, exc.pcm)
                emit("error", index, str(exc))

        try:
            if detect and self.speaker_model is None:
                self.speaker_model = SpkModel(str(SPEAKER_PATH))
            if detect and any(index == 1 and lang == 'auto' for index, _, lang in selected):
                if (DATA / 'wespeaker-resnet34.onnx').is_file() and (DATA / 'speaker-segmentation.onnx').is_file():
                    from speaker_diarization import SpeakerDiarizer
                    self.speaker_diarizer = SpeakerDiarizer(DATA)
                else:
                    self.speaker_diarizer = None
            for index, device, lang in selected:
                if stop.is_set():
                    break
                if lang == "auto" and self.whisper is None:
                    self.whisper = load_whisper(DATA / "whisper-small", DATA / "whisper-turbo")
                    diagnostics.record_model(getattr(self.whisper, 'livetranslate_model_name', None),
                                             getattr(getattr(self.whisper, 'model', None), 'device', None))
                for src in (("ru", "en") if lang == "auto" else (lang,)):
                    if src not in self.cache:
                        self.cache[src] = Language(src)
                if lang == "auto" and "de" not in self.cache and (DATA / "translate-de_en-1_9").is_dir():
                    self.cache["de"] = GermanTranslation(self.cache["en"])
            with pa.PyAudio() as audio:
                workers = []
                try:
                    for index, device, lang in selected:
                        if stop.is_set():
                            break
                        worker = threading.Thread(target=run, args=(audio, index, lang, device))
                        worker.start()
                        workers.append(worker)
                except Exception:
                    stop.set()
                    raise
                finally:
                    for worker in workers:
                        worker.join()
        except Exception as exc:
            diagnostics.log_error('session', type(exc), exc.__traceback__)
            emit("error", None, str(exc))
            stop.set()
        finally:
            emit("done", None, None)

    def poll(self):
        now = time.monotonic()
        if now - self.last_model_check >= 1:
            self.last_model_check = now
            ready = base_models_ready()
            if ready and not self.models_ready:
                self.status.set('Модели готовы. Можно начать перевод')
                self.speaker_check.configure(text='Различать голоса' if SPEAKER_PATH.is_dir() else 'Различение голосов не установлено')
                self.update_devices()
            self.models_ready = ready
            marker = DATA / '.models-installing'
            if not ready and not self.model_recovery_running and now >= self.model_recovery_next and marker.exists():
                try: signature = marker.stat().st_mtime_ns
                except OSError: signature = None
                if signature is not None and signature != self.model_recovery_failed:
                    self.model_recovery_running = True
                    events = self.events
                    def recover():
                        events.put(('model_recovery', None, (signature, recover_stale_marker(DATA))))
                    threading.Thread(target=recover, daemon=True).start()
                self.model_recovery_next = now + 5
        while not self.events.empty():
            kind, index, value = self.events.get()
            if kind == 'restart_required':
                self.restart_required = True
            elif kind == 'model_recovery':
                self.model_recovery_running = False
                signature, recovered = value
                if recovered is False:
                    self.model_recovery_failed = signature
                    self.status.set('Подготовка моделей прервалась или файлы повреждены. Повторно запустите установщик.')
                elif recovered is True:
                    self.status.set('Проверка моделей завершена. Можно начать перевод.')
            elif kind == "partial":
                if value and index not in self.preview_positions:
                    self.preview_positions[index] = (len(self.entries), self.preview_sequence)
                    self.preview_sequence += 1
                self.partials[index] = value
                self.render_preview()
            elif kind == "preview":
                if value and index not in self.preview_positions:
                    self.preview_positions[index] = (len(self.entries), self.preview_sequence)
                    self.preview_sequence += 1
                old = self.previews.get(index)
                if value and not value[1] and old and old[1]:
                    source, _, *language = value
                    old_source, old_target, *old_language = old
                    if (language[:1] == old_language[:1] and
                            (source == old_source or source.startswith(old_source + ' '))):
                        value = (source, old_target, *(language[:1] or ['…']), True)
                self.previews[index] = value
                self.render_preview()
            elif kind == "line":
                self.previews[index] = None
                self.partials[index] = ''
                source, target, *extra = value
                speaker = extra[0] if extra else None
                direction = extra[1] if len(extra) > 1 else None
                if direction and "→" in direction:
                    source_lang, target_lang = (part.strip() for part in direction.split("→", 1))
                else:
                    source_lang, target_lang = (("RU", "EN") if self.direction.current() == 1 else ("EN", "RU"))
                entry = {"time": datetime.now().strftime("%H:%M:%S"), "index": index,
                         "speaker": speaker, "from": source_lang, "to": target_lang,
                         "source": source, "target": target}
                slot = self.preview_positions.pop(index, (len(self.entries), self.preview_sequence))
                position, sequence = slot
                self.entries.insert(position, entry)
                for other, (other_position, other_sequence) in list(self.preview_positions.items()):
                    if (other_position, other_sequence) > slot:
                        self.preview_positions[other] = (other_position + 1, other_sequence)
                if position != len(self.entries) - 1 or self.preview_positions:
                    self._rendered_count = None
                if self.session_id is not None:
                    try:
                        self.storage.add_phrase(self.session_id, entry)
                    except Exception as exc:
                        self.failure = f"Не удалось сохранить фразу в историю: {exc}"
                        self.stop.set()
                self.render()
            elif kind == "ready":
                self.ready += 1
                if self.ready == self.active_count and not self.stop.is_set():
                    device = getattr(getattr(self.whisper, "model", None), "device", None)
                    suffix = " · NVIDIA GPU" if device == "cuda" else (" · CPU" if device == "cpu" else "")
                    if self.whisper is not None:
                        suffix += " · Whisper " + getattr(self.whisper, 'livetranslate_model_name', 'Small')
                    if self.current_quiet_voice and self.current_auto:
                        suffix += ' · Тихий голос'
                    self.status.set("Перевод включён" + suffix)
            elif kind == "error":
                self.failure = f"{SOURCES[index] if index is not None else 'Модели'}: {value}"
                self.status.set(self.failure + (' · Другие источники могут продолжать работу' if index is not None else ''))
            elif kind == 'unrecognized_audio':
                self.unrecognized_audio.append((index, value))
                self.recover_button.configure(state='normal')
                self.recover_button.pack(side='right', padx=(0, 8))
            elif kind == "done":
                if self.stop_timeout_job is not None:
                    self.root.after_cancel(self.stop_timeout_job)
                    self.stop_timeout_job = None
                self.stop = None
                if self.session_id is not None:
                    try:
                        self.storage.end_session(self.session_id)
                    except Exception as exc:
                        self.failure = f"Не удалось завершить сохранение истории: {exc}"
                    self.session_id = None
                if self.closing:
                    if self.unrecognized_audio:
                        self.closing = False
                        self.failure = 'Есть нераспознанные фрагменты. Сохраните их перед закрытием или закройте без сохранения.'
                    else:
                        if self.failure:
                            messagebox.showerror("Сохранение", self.failure)
                        if self.finish_close():
                            return
                self.previews.clear()
                self.partials.clear()
                self.preview_positions.clear()
                self.render_preview()
                self.direction.configure(state="readonly")
                self.refresh.configure(state="normal")
                self.check.configure(state="normal")
                self.quiet_check.configure(state="normal")
                for button in self.mode_buttons:
                    button.configure(state="normal")
                self.update_devices()
                if self.restart_required:
                    self.start.configure(text='Закрыть приложение', state='normal', command=self.force_close)
                else:
                    self.start.configure(text="Начать перевод", state="normal", command=self.toggle)
                self.status.set(self.failure or (f"Записи: {self.folder}" if self.folder else "Перевод остановлен"))
        self.poll_job = self.root.after(75, self.poll)

    def finish_close(self):
        self.library.finish_inline_rename(True)
        if not self.library.save_current():
            self.closing = False
            return False
        self.translator.close()
        self.storage.close()
        diagnostics.shutdown()
        if self.poll_job is not None:
            self.root.after_cancel(self.poll_job)
            self.poll_job = None
        if getattr(self, 'theme_job', None) is not None:
            self.root.after_cancel(self.theme_job)
            self.theme_job = None
        if self.stop_timeout_job is not None:
            self.root.after_cancel(self.stop_timeout_job)
            self.stop_timeout_job = None
        # Child widgets and temporary feedback also schedule callbacks in the
        # same Tcl interpreter. Cancel them before destroying their commands.
        for job in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.tk.call('after', 'cancel', job)
        if 'report_callback_exception' in self.root.__dict__:
            del self.root.report_callback_exception
        self.root.destroy()
        return True

    def save_unrecognized(self):
        if not self.unrecognized_audio:
            return
        folder = filedialog.askdirectory(title='Куда сохранить нераспознанные фрагменты?', parent=self.root)
        if not folder:
            return
        try:
            stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            for number, (index, pcm) in enumerate(list(self.unrecognized_audio)):
                path = Path(folder) / f'LiveTranslate-fragment-{index}-{stamp}-{number}.wav'
                with wave.open(str(path), 'wb') as output:
                    output.setparams((1, 2, 16000, 0, 'NONE', ''))
                    output.writeframes(pcm)
                self.unrecognized_audio.pop(0)
            self.recover_button.configure(state='disabled')
            self.recover_button.pack_forget()
            self.status.set('Фрагменты сохранены')
        except (OSError, wave.Error) as exc:
            self.status.set(f'Не удалось сохранить фрагменты: {exc}')

    def schedule_stop_warning(self):
        if self.stop_timeout_job is None:
            self.stop_timeout_job = self.root.after(12000, self.show_stop_warning)

    def show_stop_warning(self):
        self.stop_timeout_job = None
        if self.stop is not None:
            self.status.set('Завершение затянулось. Можно закрыть приложение; последняя фраза может не сохраниться.')
            self.start.configure(text='Закрыть приложение', state='normal', command=self.force_close)

    def force_close(self):
        if not self.confirm_discard_audio(): return
        self.closing = True
        self.finish_close()

    def confirm_discard_audio(self):
        if not self.unrecognized_audio:
            return True
        if not messagebox.askyesno(
                'Несохранённый фрагмент',
                'Есть нераспознанные фрагменты в памяти. При закрытии они будут потеряны. Закрыть без сохранения?',
                parent=self.root):
            return False
        self.unrecognized_audio.clear()
        return True

    def close(self):
        if not self.confirm_discard_audio(): return
        if self.stop is None:
            self.finish_close()
        else:
            self.closing = True
            self.stop.set()
            self.start.configure(state="disabled")
            self.status.set("Завершаем обработку…")
            self.schedule_stop_warning()


if __name__ == "__main__":
    from single_instance import SingleInstance, activate_existing, register_window
    instance = SingleInstance()
    try:
        if instance.is_primary:
            root = tk.Tk()
            App(root)
            register_window(root)
            root.mainloop()
        else:
            activate_existing()
    finally:
        instance.close()
