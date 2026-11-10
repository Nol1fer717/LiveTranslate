"""Translate growing stable prefixes without blocking speech recognition."""
import queue
import threading
import time
from collections import OrderedDict
import diagnostics


class PartialTranslator:
    def __init__(self, languages, publish):
        self.languages = languages
        self.publish = publish
        self.lock = threading.Lock()
        self.generation = 0
        self.closed = False
        self.latest = None
        self.cache = OrderedDict()
        self.requests = queue.Queue(maxsize=1)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, text, language):
        with self.lock:
            if self.closed:
                return
            item = (self.generation, text, language)
            if item == self.latest:
                return
            self.latest = item
            self._replace(item)

    def _replace(self, item):
        try:
            self.requests.put_nowait(item)
        except queue.Full:
            try:
                self.requests.get_nowait()
            except queue.Empty:
                pass
            self.requests.put_nowait(item)

    def reset(self):
        with self.lock:
            self.generation += 1
            self.latest = None

    def close(self):
        with self.lock:
            if self.closed:
                return not self.thread.is_alive()
            self.closed = True
            self.generation += 1
            self.latest = None
            self.cache.clear()
            self._replace(None)
        self.thread.join(timeout=2)
        return not self.thread.is_alive()

    def _run(self):
        generation = -1
        source = target = ''
        while True:
            item = self.requests.get()
            if item is None:
                return
            current, text, language = item
            if current != generation:
                generation, source, target = current, '', ''
                with self.lock:
                    candidates = [(old_text, translation) for (old_language, old_text), translation in self.cache.items()
                                  if old_language == language and (text == old_text or text.startswith(old_text + ' '))]
                if candidates:
                    source, target = max(candidates, key=lambda item: len(item[0]))
            if text == source:
                with self.lock:
                    if current == self.generation and item == self.latest:
                        self.publish((text, target, language.upper()))
                continue
            extends = bool(source and text.startswith(source) and len(text) > len(source) and text[len(source)].isspace())
            extra = text[len(source):].strip() if extends else text
            if not extra or language not in self.languages:
                continue
            if not extends:
                source = target = ''
            try:
                started = time.monotonic()
                translated = self.languages[language].translate(extra)
                diagnostics.record_timing('partial_translation', time.monotonic() - started)
            except Exception as exc:
                diagnostics.log_error('partial_translation', type(exc), exc.__traceback__)
                with self.lock:
                    if current == self.generation and item == self.latest:
                        self.publish((text, 'Предварительный перевод недоступен', language.upper()))
                continue
            source = text
            target = (target + ' ' + translated).strip()
            with self.lock:
                if current == self.generation:
                    key = (language, text)
                    self.cache[key] = target
                    self.cache.move_to_end(key)
                    while len(self.cache) > 64:
                        self.cache.popitem(last=False)
                if current == self.generation and item == self.latest:
                    self.publish((text, target, language.upper()))
