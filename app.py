import queue
import os
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

import pyaudiowpatch as pa
from vosk import SpkModel

from engine import DATA, GermanTranslation, Language, SPEAKER_PATH, capture, devices
from whisper_stream import load_whisper
from storage import Storage
from library_ui import LibraryUI
from translator_ui import TranslatorUI
from user_data import data_directory
from rounded_button import RoundedButton
from settings import read_split_level, save_split_level
from theme import BG, CARD, FIELD, TEXT, MUTED, ACCENT, ACCENT_DARK, ACCENT_SOFT, BORDER, HOVER, SELECTION

SOURCES = ("Микрофон", "Звук компьютера")
DIRECTIONS = ("Автоопределение", "Русский → Английский", "Английский → Русский")
MODES = ("Микрофон", "Звук компьютера", "Микрофон + компьютер")
VIEWS = ("Оба", "Транскрипция", "Перевод")
BLUE, PURPLE = ACCENT, ACCENT_DARK


def base_models_ready():
    required = ('whisper-small/model.bin', 'whisper-small/config.json', 'whisper-small/tokenizer.json',
                'translate-en_ru-1_9/model/model.bin', 'translate-ru_en-1_9/model/model.bin',
                'vosk-model-small-en-us-0.15/am/final.mdl', 'vosk-model-small-ru-0.22/am/final.mdl')
    return all((DATA / name).is_file() for name in required)


class App:
    def __init__(self, root):
        self.root = root
        root.title("LiveTranslate")
        root.geometry("980x760")
        root.minsize(760, 600)
        root.configure(bg=BG)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Dark.TCombobox", fieldbackground=FIELD, background=FIELD,
                        foreground=TEXT, arrowcolor=MUTED, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=8)
        style.map("Dark.TCombobox", fieldbackground=[("readonly", FIELD)],
                  foreground=[("readonly", TEXT)])
        style.configure("Vertical.TScrollbar", background=BORDER, troughcolor=CARD, bordercolor=CARD,
                        arrowcolor=MUTED)

        masthead = tk.Frame(root, bg=CARD, padx=28, pady=14, highlightbackground=BORDER, highlightthickness=1)
        masthead.grid(row=0, column=0, sticky="ew")
        tk.Label(masthead, text="LiveTranslate", bg=CARD, fg=TEXT, font=("Segoe UI", 17, "bold")).pack(side="left")
        tk.Label(masthead, text="Перевод и изучение языков", bg=CARD, fg=MUTED, font=("Segoe UI", 10)).pack(side="left", padx=(16, 0))
        style.configure("Modern.TNotebook", background=BG, borderwidth=0)
        style.layout("Modern.TNotebook.Tab", [])
        navigation = tk.Frame(root, bg=BG, padx=24, pady=8)
        navigation.grid(row=1, column=0, sticky="ew")
        tabs = ttk.Notebook(root, style="Modern.TNotebook")
        tabs.grid(row=2, column=0, sticky="nsew")
        page = tk.Frame(tabs, bg=BG, padx=28, pady=20)
        tabs.add(page, text="Перевод")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(4, weight=1)

        header = tk.Frame(page, bg=BG)
        header.grid(row=0, sticky="ew", pady=(0, 20))
        tk.Label(header, text="Перевод", bg=BG, fg=TEXT,
                 font=("Segoe UI", 19, "bold")).pack(side="left")
        self.status = tk.StringVar(value="Выберите источник и начните перевод")
        tk.Label(header, textvariable=self.status, bg=BG, fg=MUTED,
                 font=("Segoe UI", 10), anchor="e").pack(side="right", fill="x", expand=True, padx=(18, 0))

        controls = tk.Frame(page, bg=CARD, padx=18, pady=16, highlightthickness=1,
                            highlightbackground=BORDER)
        controls.grid(row=1, sticky="ew", pady=(0, 18))
        controls.columnconfigure(0, weight=1)

        top = tk.Frame(controls, bg=CARD)
        top.grid(row=0, sticky="ew")
        tk.Label(top, text="Язык", bg=CARD, fg=MUTED, font=("Segoe UI", 10)).pack(side="left", padx=(0, 10))
        self.direction = ttk.Combobox(top, values=DIRECTIONS, state="readonly", width=25, style="Dark.TCombobox")
        self.direction.current(0)
        self.direction.pack(side="left")
        self.start = RoundedButton(top, text="Начать перевод", command=self.toggle, bg=ACCENT, fg="white",
                               activebackground=ACCENT_DARK, activeforeground="white", relief="flat",
                               padx=20, pady=8, cursor="hand2", font=("Segoe UI", 10, "bold"))
        self.start.pack(side="right")

        self.mode = tk.StringVar(value=MODES[2])
        self.mode_buttons = []
        mode_bar = tk.Frame(controls, bg=CARD)
        mode_bar.grid(row=1, sticky="ew", pady=(16, 6))
        for label in MODES:
            button = RoundedButton(mode_bar, text=label, command=lambda value=label: self.set_mode(value),
                               relief="flat", padx=14, pady=7, cursor="hand2", font=("Segoe UI", 10, "bold"))
            button.pack(side="left", padx=(0, 6))
            self.mode_buttons.append(button)

        choices = tk.Frame(controls, bg=CARD)
        choices.grid(row=2, sticky="ew", pady=(8, 0))
        choices.columnconfigure((0, 1), weight=1, uniform="device")
        self.device_boxes = []
        for index, title in enumerate(SOURCES):
            group = tk.Frame(choices, bg=CARD)
            group.grid(row=0, column=index, sticky="ew", padx=(0, 8) if index == 0 else (8, 0))
            group.columnconfigure(0, weight=1)
            tk.Label(group, text=title, bg=CARD, fg=MUTED, font=("Segoe UI", 9)).grid(sticky="w", pady=(0, 4))
            box = ttk.Combobox(group, state="readonly", style="Dark.TCombobox", width=18)
            box.grid(row=1, column=0, sticky="ew")
            self.device_boxes.append(box)

        options = tk.Frame(controls, bg=CARD)
        options.grid(row=3, sticky="ew", pady=(10, 0))
        self.identify = tk.BooleanVar(value=SPEAKER_PATH.is_dir())
        self.speaker_check = tk.Checkbutton(options,
                                            text="Различать голоса" if SPEAKER_PATH.is_dir() else "Различение голосов не установлено",
                                            variable=self.identify,
                                            bg=CARD, fg=TEXT, selectcolor=FIELD, activebackground=CARD,
                                            activeforeground=TEXT, highlightthickness=0)
        self.speaker_check.pack(side="left")
        self.save = tk.BooleanVar()
        self.check = tk.Checkbutton(options, text="Сохранять звук в WAV", variable=self.save,
                                    bg=CARD, fg=TEXT, selectcolor=FIELD, activebackground=CARD,
                                    activeforeground=TEXT, highlightthickness=0)
        self.check.pack(side="left", padx=(18, 0))
        self.refresh = RoundedButton(options, text="Обновить устройства", command=self.scan, bg=CARD, fg=BLUE,
                                 activebackground=FIELD, activeforeground=TEXT, relief="flat", cursor="hand2")
        self.refresh.pack(side="right")

        view_bar = tk.Frame(page, bg=BG)
        view_bar.grid(row=2, sticky="ew", pady=(0, 10))
        self.view = tk.StringVar(value=VIEWS[0])
        self.view_buttons = []
        for label in VIEWS:
            button = RoundedButton(view_bar, text=label, command=lambda value=label: self.set_view(value),
                               relief="flat", padx=16, pady=7, cursor="hand2", font=("Segoe UI", 10, "bold"))
            button.pack(side="left", padx=(0, 4))
            self.view_buttons.append(button)

        results = tk.Frame(page, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        results.grid(row=4, sticky="nsew")
        results.rowconfigure(0, weight=1)
        results.columnconfigure(0, weight=1)
        self.history = tk.Text(results, wrap="word", bg=CARD, fg=TEXT, insertbackground=TEXT,
                               selectbackground=SELECTION, selectforeground=TEXT, relief="flat", padx=20, pady=18,
                               font=("Segoe UI", 12), state="disabled", cursor="arrow")
        self.history.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(results, orient="vertical", command=self.history.yview, style="Vertical.TScrollbar")
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=8)
        self.history.configure(yscrollcommand=scrollbar.set)
        self.history.tag_configure("meta", foreground=MUTED, font=("Segoe UI", 9), spacing1=12, spacing3=6)
        self.history.tag_configure("source_label", foreground=BLUE, font=("Segoe UI", 10, "bold"))
        self.history.tag_configure("target_label", foreground=PURPLE, font=("Segoe UI", 10, "bold"))
        self.history.tag_configure("source", foreground=MUTED, font=("Segoe UI", 12), spacing3=6)
        self.history.tag_configure("target", foreground=TEXT, font=("Segoe UI", 13), spacing3=12)
        self.history.tag_configure("placeholder", foreground=MUTED, font=("Segoe UI", 11))

        self.storage = Storage()
        if self.storage.legacy_conflict:
            messagebox.showwarning("История и заметки", "В «Документах» уже есть своя база. Она сохранена без изменений; старая база в AppData тоже сохранена, но автоматически с ней не объединена.", parent=root)
        self.translator = TranslatorUI(tabs)
        self.library = LibraryUI(tabs, self.storage)
        self.settings_path = data_directory() / 'settings.json'
        self.split_level = tk.IntVar(value=read_split_level(self.settings_path))
        self.settings_page = tk.Frame(tabs, bg=BG, padx=28, pady=20)
        tabs.add(self.settings_page, text='Настройки')
        tk.Label(self.settings_page, text='Настройки', bg=BG, fg=TEXT, font=('Segoe UI', 19, 'bold')).pack(anchor='w')
        card = tk.Frame(self.settings_page, bg=CARD, padx=20, pady=18, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill='x', pady=(18, 0))
        tk.Label(card, text='Скорость разбиения высказываний', bg=CARD, fg=TEXT, font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        tk.Label(card, text='1 — чаще, 10 — реже. Изменение применяется при следующем запуске перевода.', bg=CARD, fg=MUTED, wraplength=750, justify='left').pack(anchor='w', pady=(6, 8))
        scale = tk.Scale(card, from_=1, to=10, orient='horizontal', resolution=1, variable=self.split_level,
                         bg=CARD, fg=TEXT, activebackground=ACCENT, highlightthickness=0, troughcolor=ACCENT_SOFT,
                         length=430, showvalue=True)
        scale.pack(anchor='w', fill='x')
        scale.bind('<ButtonRelease-1>', self.save_settings)
        scale.bind('<KeyRelease>', self.save_settings)
        tk.Label(card, text='Речь отображается предварительно, перевод появляется после завершения фрагмента.', bg=CARD, fg=MUTED, wraplength=750, justify='left').pack(anchor='w', pady=(10, 0))
        nav_buttons = []
        for label, target in (("Перевод", page), ("Переводчик", self.translator.page), ("История", self.library.history_page), ("Заметки", self.library.notes_page), ("Настройки", self.settings_page)):
            control = RoundedButton(navigation, text=label, command=lambda selected=target: tabs.select(selected),
                                relief="flat", padx=18, pady=7, cursor="hand2", font=("Segoe UI", 10, "bold"),
                                activebackground=HOVER, activeforeground=ACCENT)
            control.pack(side="left", padx=(0, 6))
            nav_buttons.append((control, target))

        def update_navigation(event=None):
            current = tabs.select()
            for control, target in nav_buttons:
                active = current == str(target)
                control.configure(bg=ACCENT_SOFT if active else BG, fg=ACCENT if active else MUTED)
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
        self.stop = None
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
        if not self.models_ready:
            self.status.set('Загрузка моделей выполняется в фоне')
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_job = None
        self.poll()

    def set_mode(self, mode):
        self.mode.set(mode)
        for button, label in zip(self.mode_buttons, MODES):
            selected = label == mode
            button.configure(bg=ACCENT_SOFT if selected else CARD, fg=ACCENT if selected else TEXT,
                             activebackground=HOVER, activeforeground=TEXT)
        self.update_devices()

    def save_settings(self, event=None):
        try:
            save_split_level(self.settings_path, self.split_level.get())
        except (OSError, ValueError, tk.TclError) as exc:
            messagebox.showerror('Настройки', f'Не удалось сохранить настройки: {exc}', parent=self.root)

    def update_devices(self):
        active = (self.mode.get() != MODES[1], self.mode.get() != MODES[0])
        for index, box in enumerate(self.device_boxes):
            box.configure(state="readonly" if active[index] and self.stop is None else "disabled")
        self.speaker_check.configure(state="normal" if active[1] and self.stop is None and SPEAKER_PATH.is_dir() else "disabled")

    def set_view(self, view):
        self.view.set(view)
        for button, label in zip(self.view_buttons, VIEWS):
            button.configure(bg=ACCENT_SOFT if label == view else BG,
                             fg=ACCENT if label == view else MUTED,
                             activebackground=HOVER, activeforeground=TEXT)
        self.render()
        self.render_preview()

    def scan(self):
        try:
            self.device_items = list(devices())
            for box, items in zip(self.device_boxes, self.device_items):
                box.configure(values=[d["name"] for d in items])
                if items:
                    box.current(0)
            self.status.set("Выберите источник и начните перевод")
            self.update_devices()
        except Exception as exc:
            self.status.set(f"Не удалось получить устройства: {exc}")

    def render(self):
        selected = self.history.tag_ranges("sel")
        selected_text = self.history.get("sel.first", "sel.last") if selected else None
        scroll = self.history.yview()[0] if selected else None
        self.history.configure(state="normal")
        self.history.delete("1.0", "end")
        if not self.entries and not any(self.previews.values()) and not any(self.partials.values()):
            self.history.insert("end", "Здесь появятся распознанная речь и перевод.", "placeholder")
        for entry in self.entries:
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
        for index, value in self.previews.items():
            if not value:
                continue
            source, target, *language = value
            source_lang = language[0] if language else "…"
            target_lang = "EN" if source_lang == "RU" else "RU"
            self.history.insert("end", f"{SOURCES[index]} · Распознавание\n", "meta")
            if self.view.get() != VIEWS[2]:
                self.history.insert("end", f"[{source_lang}]  ", "source_label")
                self.history.insert("end", source + "\n", "source")
            if self.view.get() != VIEWS[1] and target:
                self.history.insert("end", f"[{target_lang}]  ", "target_label")
                self.history.insert("end", target + "\n", "target")
        if self.view.get() != VIEWS[2]:
            for index, partial in self.partials.items():
                if partial and not self.previews.get(index):
                    self.history.insert("end", f"{SOURCES[index]} · Распознавание\n", "meta")
                    self.history.insert("end", partial + "\n", "source")
        if selected_text:
            match = self.history.search(selected_text, "1.0", stopindex="end", exact=True)
            if match:
                self.history.tag_add("sel", match, f"{match}+{len(selected_text)}c")
                self.history.yview_moveto(scroll)
        else:
            self.history.see("end")
        self.history.configure(state="disabled")

    def render_preview(self):
        self.render()

    def toggle(self):
        if self.stop is not None:
            self.stop.set()
            self.start.configure(state="disabled")
            self.status.set("Завершаем обработку…")
            return
        if not base_models_ready():
            messagebox.showinfo('Подготовка моделей', 'Модели ещё загружаются в фоне после установки. Дождитесь окончания подготовки. Если загрузка не завершилась, запустите установщик повторно.')
            return
        indices = ((0,), (1,), (0, 1))[MODES.index(self.mode.get())]
        selected = []
        for index in indices:
            position = self.device_boxes[index].current()
            if position < 0:
                messagebox.showerror("Устройство", f"Не найдено устройство: {SOURCES[index]}")
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
        for button in self.mode_buttons:
            button.configure(state="disabled")
        self.update_devices()
        self.start.configure(text="Остановить")
        self.status.set("Подготавливаем модели и устройства…")
        detect = self.identify.get() and any(index == 1 for index, _, _ in selected)
        self.current_split_level = self.split_level.get()
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
                        index, stop, emit, path, speaker_model, self.whisper if lang == "auto" else None,
                        diarizer=diarizer, split_level=self.current_split_level)
            except Exception as exc:
                emit("error", index, str(exc))
                stop.set()

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
        while not self.events.empty():
            kind, index, value = self.events.get()
            if kind == "partial":
                self.partials[index] = value
                self.render_preview()
            elif kind == "preview":
                self.previews[index] = value
                self.render_preview()
            elif kind == "line":
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
                self.entries.append(entry)
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
                    self.status.set("Перевод включён" + suffix)
            elif kind == "error":
                self.failure = f"{SOURCES[index] if index is not None else 'Модели'}: {value}"
            elif kind == "done":
                self.stop = None
                if self.session_id is not None:
                    try:
                        self.storage.end_session(self.session_id)
                    except Exception as exc:
                        self.failure = f"Не удалось завершить сохранение истории: {exc}"
                    self.session_id = None
                if self.closing:
                    if self.failure:
                        messagebox.showerror("Сохранение", self.failure)
                    if self.finish_close():
                        return
                self.previews.clear()
                self.partials.clear()
                self.render_preview()
                self.direction.configure(state="readonly")
                self.refresh.configure(state="normal")
                self.check.configure(state="normal")
                for button in self.mode_buttons:
                    button.configure(state="normal")
                self.update_devices()
                self.start.configure(text="Начать перевод", state="normal")
                self.status.set(self.failure or (f"Записи: {self.folder}" if self.folder else "Перевод остановлен"))
        self.poll_job = self.root.after(75, self.poll)

    def finish_close(self):
        self.library.finish_inline_rename(True)
        if not self.library.save_current():
            self.closing = False
            return False
        self.translator.close()
        self.storage.close()
        if self.poll_job is not None:
            self.root.after_cancel(self.poll_job)
            self.poll_job = None
        self.root.destroy()
        return True

    def close(self):
        if self.stop is None:
            self.finish_close()
        else:
            self.closing = True
            self.stop.set()
            self.start.configure(state="disabled")
            self.status.set("Завершаем обработку…")


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
