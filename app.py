import queue
import threading
import tkinter as tk
import pyaudiowpatch as pa
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from vosk import SpkModel
from engine import DATA, Language, SPEAKER_PATH, capture, devices
from whisper_stream import load_whisper

SOURCES = ("Микрофон", "Звук компьютера")
DIRECTIONS = ("Авто · Whisper", "Русский → Английский", "Английский → Русский")


class Channel:
    def __init__(self, parent, index):
        panel = ttk.Frame(parent, padding=(16, 12), style="Card.TFrame")
        panel.grid(row=index + 1, column=0, sticky="nsew", pady=(0, 10))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)
        header = ttk.Frame(panel, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=SOURCES[index], style="Title.TLabel").pack(side="left")
        if index == 1:
            available = SPEAKER_PATH.is_dir()
            self.identify = tk.BooleanVar(value=available)
            self.speaker_check = ttk.Checkbutton(header, text="Различать голоса" if available else "Модель голосов не установлена",
                                                 variable=self.identify, style="Card.TCheckbutton",
                                                 state="normal" if available else "disabled")
            self.speaker_check.pack(side="left", padx=(10, 0))
        self.direction = ttk.Combobox(panel, values=DIRECTIONS, state="readonly", width=23)
        self.direction.current(0)
        self.direction.grid(row=0, column=1, sticky="e")
        self.device = ttk.Combobox(panel, state="readonly")
        self.device.grid(row=1, column=0, columnspan=2, sticky="ew", pady=7)
        self.history = tk.Text(panel, wrap="word", height=4, relief="flat", bg="#f4f7f8",
                               padx=10, pady=6, state="disabled", font=("Segoe UI", 13))
        self.history.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.history.tag_configure("source", foreground="#55676d", font=("Segoe UI", 10))
        self.history.tag_configure("target", foreground="#132c35", spacing3=8)
        self.history.tag_configure("speaker", foreground="#085c58", font=("Segoe UI", 10, "bold"))
        self.partial = tk.StringVar()
        ttk.Label(panel, textvariable=self.partial, style="Partial.TLabel", anchor="w").grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    def options(self, devices):
        self.items = [None, *devices]
        names = ["Отключён", *(d["name"] for d in devices)]
        self.device.configure(values=names)
        self.device.current(1 if devices else 0)

    def line(self, source, target, speaker=None, direction=None):
        self.history.configure(state="normal")
        label = " · ".join(item for item in (speaker, direction) if item)
        if label:
            self.history.insert("end", label + "\n", "speaker")
        self.history.insert("end", source + "\n", "source")
        self.history.insert("end", target + "\n", "target")
        self.history.see("end")
        self.history.configure(state="disabled")

    def start_session(self):
        if self.history.compare("end-1c", ">", "1.0"):
            self.history.configure(state="normal")
            self.history.insert("end", "Новый сеанс · " + datetime.now().strftime("%H:%M") + "\n", "source")
            self.history.configure(state="disabled")


class App:
    def __init__(self, root):
        self.root = root
        root.title("Переводчик речи")
        root.geometry("800x700")
        root.minsize(610, 490)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#edf2f3")
        style.configure("Card.TFrame", background="white")
        style.configure("Title.TLabel", background="white", foreground="#162e39", font=("Segoe UI", 13, "bold"))
        style.configure("Partial.TLabel", background="white", foreground="#517068")
        style.configure("TCheckbutton", background="#edf2f3")
        style.configure("Card.TCheckbutton", background="white")
        root.configure(background="#edf2f3")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        page = ttk.Frame(root, padding=16)
        page.grid(sticky="nsew")
        page.columnconfigure(0, weight=1)
        for row in (1, 2):
            page.rowconfigure(row, weight=1)
        ttk.Label(page, text="Перевод разговора", font=("Segoe UI", 20, "bold"),
                  foreground="#17343b", background="#edf2f3").grid(row=0, sticky="w", pady=(0, 12))
        self.channels = [Channel(page, i) for i in range(2)]
        bar = ttk.Frame(page)
        bar.grid(row=3, sticky="ew")
        self.start = ttk.Button(bar, text="Начать перевод", command=self.toggle)
        self.start.pack(side="left")
        self.refresh = ttk.Button(bar, text="Обновить устройства", command=self.scan)
        self.refresh.pack(side="left", padx=8)
        self.save = tk.BooleanVar()
        self.check = ttk.Checkbutton(bar, text="Сохранять звук в WAV", variable=self.save)
        self.check.pack(side="right")
        self.status = tk.StringVar(value="Выберите устройства и начните перевод.")
        ttk.Label(page, textvariable=self.status, background="#edf2f3", wraplength=640,
                  foreground="#344e54").grid(row=4, sticky="w", pady=(8, 0))
        self.events = queue.SimpleQueue()
        self.stop = None
        self.closing = False
        self.cache = {}
        self.speaker_model = None
        self.whisper = None
        self.scan()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll()

    def scan(self):
        try:
            lists = devices()
            for channel, items in zip(self.channels, lists):
                channel.options(items)
            self.status.set("Выберите устройства и начните перевод.")
        except Exception as exc:
            for channel in self.channels:
                channel.options([])
            self.status.set(f"Ошибка получения устройств: {exc}")

    def toggle(self):
        if self.stop is not None:
            self.stop.set()
            self.start.configure(state="disabled")
            self.status.set("Завершение последней фразы…")
            return
        selected = []
        for index, channel in enumerate(self.channels):
            device = channel.items[channel.device.current()]
            if device:
                lang = ("auto", "ru", "en")[channel.direction.current()]
                selected.append((index, device, lang))
        if not selected:
            self.status.set("Выберите хотя бы одно устройство.")
            return
        folder = None
        if self.save.get():
            folder = Path.home() / "Documents" / "VoiceTranslator Recordings" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            try:
                folder.mkdir(parents=True)
            except OSError as exc:
                messagebox.showerror("Запись", str(exc))
                return
        self.folder = folder
        self.stop = threading.Event()
        self.failure = ""
        self.active_count = len(selected)
        self.ready = 0
        for channel in self.channels:
            channel.direction.configure(state="disabled")
            channel.device.configure(state="disabled")
        self.refresh.configure(state="disabled")
        self.check.configure(state="disabled")
        self.channels[1].speaker_check.configure(state="disabled")
        self.start.configure(text="Остановить")
        self.status.set("Подготовка моделей и устройств…")
        detect = self.channels[1].identify.get() and any(index == 1 for index, _, _ in selected)
        threading.Thread(target=self.session, args=(selected, folder, self.stop, detect), daemon=True).start()

    def session(self, selected, folder, stop, detect):
        def emit(kind, index, value):
            self.events.put((kind, index, value))

        def run(audio, index, device, lang):
            try:
                path = folder / ("microphone.wav", "computer.wav")[index] if folder else None
                speaker_model = self.speaker_model if index == 1 and detect else None
                automatic = lang == "auto"
                capture(audio, device, self.cache if automatic else self.cache[lang],
                        index, stop, emit, path, speaker_model, self.whisper if automatic else None)
            except Exception as exc:
                emit("error", index, str(exc))
                stop.set()

        workers = []
        try:
            if detect and self.speaker_model is None:
                self.speaker_model = SpkModel(str(SPEAKER_PATH))
            for index, device, lang in selected:
                if stop.is_set():
                    break
                if lang == "auto" and self.whisper is None:
                    self.whisper = load_whisper(DATA / "whisper-base")
                for src in (("ru", "en") if lang == "auto" else (lang,)):
                    if src not in self.cache:
                        self.cache[src] = Language(src)
            with pa.PyAudio() as audio:
                try:
                    for item in selected:
                        if stop.is_set():
                            break
                        worker = threading.Thread(target=run, args=(audio, *item))
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
        while not self.events.empty():
            kind, index, value = self.events.get()
            if kind == "partial":
                self.channels[index].partial.set(value)
            elif kind == "line":
                self.channels[index].line(*value)
            elif kind == "ready":
                self.channels[index].start_session()
                self.ready += 1
                if self.ready == self.active_count and not self.stop.is_set():
                    self.status.set("Идёт перевод. Говорите в микрофон или включите речь на компьютере.")
            elif kind == "error":
                name = SOURCES[index] if index is not None else "Модели"
                self.failure = f"{name}: {value}"
            elif kind == "done":
                self.stop = None
                if self.closing:
                    self.root.destroy()
                    return
                for channel in self.channels:
                    channel.device.configure(state="readonly")
                    channel.direction.configure(state="readonly")
                    channel.partial.set("")
                self.refresh.configure(state="normal")
                self.check.configure(state="normal")
                self.channels[1].speaker_check.configure(state="normal" if SPEAKER_PATH.is_dir() else "disabled")
                self.start.configure(text="Начать перевод", state="normal")
                self.status.set(self.failure or (f"Записи: {self.folder}" if self.folder else "Перевод остановлен."))
        self.root.after(75, self.poll)

    def close(self):
        if self.stop is None:
            self.root.destroy()
        else:
            self.closing = True
            self.toggle()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
