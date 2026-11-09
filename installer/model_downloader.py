"""Download and verify only the models needed by a LiveTranslate installation."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import queue
import shutil
import sys
import tarfile
import threading
import time
from urllib.request import Request, urlopen
from gpu_detection import nvidia_memory, supports_turbo

CONFIG = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'packages.json'
CHUNK = 1024 * 1024


def file_digest(path, cancelled):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while data := source.read(CHUNK):
            if cancelled.is_set():
                raise InterruptedError('Загрузка отменена')
            digest.update(data)
    return digest.hexdigest()


def existing_valid(package, target, cancelled):
    for entry in package['files']:
        path = target / entry['path']
        if not path.is_file() or file_digest(path, cancelled) != entry['sha256']:
            return False
    return True


def download(package, output, cancelled, notify):
    destination = output / package['name']
    temporary = output / (package['name'] + '.part')
    last_error = None
    for attempt in range(3):
        if cancelled.is_set():
            raise InterruptedError('Загрузка отменена')
        try:
            if package.get('hf_file'):
                from huggingface_hub import hf_hub_download
                path = Path(hf_hub_download(repo_id=package['hf_repo'], filename=package['hf_file'],
                                            revision=package['hf_revision'], local_dir=output / 'hf-turbo'))
                if file_digest(path, cancelled) != package['sha256']:
                    raise ValueError(f"Не совпала контрольная сумма: {package['name']}")
                shutil.move(str(path), str(destination))
                notify(destination.stat().st_size)
                return
            digest = hashlib.sha256()
            agent = 'Mozilla/5.0' if package['name'] == 'translate-en_de-1_3.zip' else 'LiveTranslate-Installer/1.3'
            request = Request(package['url'], headers={'User-Agent': agent})
            with urlopen(request, timeout=30) as response, temporary.open('wb') as target:
                while data := response.read(CHUNK):
                    if cancelled.is_set():
                        raise InterruptedError('Загрузка отменена')
                    digest.update(data)
                    target.write(data)
                    notify(len(data))
            if digest.hexdigest() != package['sha256']:
                raise ValueError(f"Не совпала контрольная сумма: {package['name']}")
            if package.get('archive_member'):
                extracted = output / (package['name'] + '.extracted')
                try:
                    with tarfile.open(temporary, 'r:bz2') as archive:
                        member = archive.getmember(package['archive_member'])
                        if not member.isfile() or member.size > 20_000_000:
                            raise ValueError('Некорректный файл модели в архиве')
                        with archive.extractfile(member) as source, extracted.open('wb') as target:
                            shutil.copyfileobj(source, target, CHUNK)
                    if file_digest(extracted, cancelled) != package['files'][0]['sha256']:
                        raise ValueError('Не совпала контрольная сумма модели')
                    extracted.replace(destination)
                    temporary.unlink(missing_ok=True)
                    return
                finally:
                    extracted.unlink(missing_ok=True)
            temporary.replace(destination)
            return
        except (OSError, ValueError) as exc:
            last_error = exc
            temporary.unlink(missing_ok=True)
            if attempt < 2 and not cancelled.is_set():
                time.sleep(attempt + 1)
    raise RuntimeError(f"Не удалось скачать {package['name']}: {last_error}")


def prepare(target, output, tasks, cancelled, updates):
    packages = json.loads(CONFIG.read_text(encoding='utf-8'))
    active = [p for p in packages if p['task'] is None or p['task'] in tasks]
    output.mkdir(parents=True, exist_ok=True)
    needed = []
    for package in active:
        updates.put(('status', 'Проверяем уже установленные компоненты…'))
        if not existing_valid(package, target, cancelled):
            needed.append(package)
    if not needed:
        updates.put(('status', 'Все необходимые компоненты уже установлены.'))
        return
    updates.put(('status', f'Параллельная загрузка компонентов: {len(needed)}'))
    with ThreadPoolExecutor(max_workers=min(4, len(needed))) as pool:
        futures = {pool.submit(download, package, output, cancelled,
                               lambda count: updates.put(('bytes', count))): package for package in needed}
        optional_failed = False
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                if futures[future]['task'] in ('nvidia', 'turbo') and not cancelled.is_set():
                    optional_failed = True
                    continue
                cancelled.set()
                raise
    if optional_failed:
        # Do not install a partial GPU/model set; the base Small CPU build works.
        for package in needed:
            if package['task'] in ('nvidia', 'turbo'):
                (output / package['name']).unlink(missing_ok=True)
        updates.put(('status', 'Не удалось загрузить ускорение. Установка продолжится с Whisper Small на CPU.'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tasks', default='')
    parser.add_argument('--silent', action='store_true')
    parser.add_argument('--auto-gpu', action='store_true')
    args = parser.parse_args()
    tasks = set(filter(None, args.tasks.split(',')))
    if args.auto_gpu:
        memory = nvidia_memory()
        if memory:
            tasks.add('nvidia')
        if supports_turbo(memory, check_free=False):
            tasks.add('turbo')
    cancelled, updates = threading.Event(), queue.SimpleQueue()
    if args.silent:
        try:
            prepare(args.target, args.output, tasks, cancelled, updates)
            return 0
        except Exception as exc:
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / 'error.log').write_text(str(exc), encoding='utf-8')
            return 1
    import tkinter as tk
    from tkinter import messagebox, ttk
    root = tk.Tk()
    root.title('LiveTranslate — подготовка компонентов')
    root.resizable(False, False)
    root.geometry('480x160')
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    title = ttk.Label(frame, text='Подготовка LiveTranslate', font=('Segoe UI', 13, 'bold'))
    title.pack(anchor='w')
    status = tk.StringVar(value='Проверяем компоненты…')
    ttk.Label(frame, textvariable=status).pack(anchor='w', pady=(12, 4))
    detail = tk.StringVar(value='')
    ttk.Label(frame, textvariable=detail).pack(anchor='w')
    cancel_button = ttk.Button(frame, text='Отмена', command=cancelled.set)
    cancel_button.pack(anchor='e', pady=(6, 0))
    root.protocol('WM_DELETE_WINDOW', cancelled.set)
    state = {'result': None, 'bytes': 0}
    def run():
        try:
            prepare(args.target, args.output, tasks, cancelled, updates)
            state['result'] = 1 if cancelled.is_set() else 0
        except Exception as exc:
            state['result'] = 1
            updates.put(('error', str(exc)))
    threading.Thread(target=run, daemon=True).start()
    def tick():
        while not updates.empty():
            kind, value = updates.get()
            if kind == 'status': status.set(value)
            elif kind == 'bytes':
                state['bytes'] += value
                detail.set(f"Скачано: {state['bytes'] / (1024 * 1024):.0f} МБ")
            else: messagebox.showerror('Загрузка компонентов', value, parent=root)
        if cancelled.is_set():
            status.set('Отменяем загрузку…')
            cancel_button.configure(state='disabled')
        if state['result'] is None:
            root.after(100, tick)
        else:
            root.destroy()
    root.after(100, tick)
    root.mainloop()
    return state['result'] or 0

if __name__ == '__main__':
    raise SystemExit(main())
