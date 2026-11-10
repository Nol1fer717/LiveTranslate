"""Download and verify only the models needed by a LiveTranslate installation."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
import tempfile
from urllib.request import Request, urlopen
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gpu_detection import nvidia_memory, supports_turbo
import diagnostics

CONFIG = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'packages.json'
CHUNK = 1024 * 1024
HF_TIMEOUT_SECONDS = 900
# Frozen windowed executables have no stdout/stderr. Hugging Face's console
# progress bar otherwise fails before a download can start.
os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'


class ProgressTimeout:
    """Time out on stalled downloads, not on total transfer duration."""
    def __init__(self, now, timeout=HF_TIMEOUT_SECONDS):
        self.last_change = now
        self.last_size = 0
        self.timeout = timeout

    def stalled(self, now, size):
        if size != self.last_size:
            self.last_size = size
            self.last_change = now
        return now - self.last_change > self.timeout


def observed_download_size(directory):
    if not directory.exists():
        return 0
    size = 0
    for item in directory.rglob('*.incomplete'):
        try:
            size += item.stat().st_size
        except FileNotFoundError:
            # The downloader can finish and rename a temporary file concurrently.
            continue
    return size


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
                local_dir = output / ('hf-' + package['name'])
                command = [sys.executable]
                if not getattr(sys, 'frozen', False): command.append(str(Path(__file__).resolve()))
                command.extend(['--hf-worker', package['hf_repo'], package['hf_file'], package['hf_revision'], str(local_dir)])
                process = subprocess.Popen(command, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                deadline, last_size = ProgressTimeout(time.monotonic()), 0
                try:
                    while process.poll() is None:
                        size = observed_download_size(local_dir)
                        if cancelled.is_set() or deadline.stalled(time.monotonic(), size):
                            process.terminate(); process.wait(timeout=10)
                            if cancelled.is_set(): raise InterruptedError('Загрузка отменена')
                            raise TimeoutError(f"Превышено время загрузки {package['name']}")
                        if size > last_size: notify(size - last_size)
                        last_size = size
                        time.sleep(0.5)
                    if process.returncode:
                        raise OSError(f"Ошибка загрузки {package['name']} (код {process.returncode})")
                finally:
                    if process.poll() is None:
                        process.terminate(); process.wait(timeout=10)
                path = local_dir / package['hf_file']
                if file_digest(path, cancelled) != package['sha256']:
                    raise ValueError(f"Не совпала контрольная сумма: {package['name']}")
                shutil.move(str(path), str(destination))
                notify(max(0, destination.stat().st_size - last_size))
                return
            digest = hashlib.sha256()
            offset = temporary.stat().st_size if temporary.is_file() else 0
            if offset:
                with temporary.open('rb') as previous:
                    while data := previous.read(CHUNK):
                        if cancelled.is_set(): raise InterruptedError('Загрузка отменена')
                        digest.update(data)
            if not offset or digest.hexdigest() != package['sha256']:
                agent = 'Mozilla/5.0' if package['name'] == 'translate-en_de-1_3.zip' else 'LiveTranslate-Installer/1.3'
                headers = {'User-Agent': agent}
                if offset: headers['Range'] = f'bytes={offset}-'
                request = Request(package['url'], headers=headers)
                with urlopen(request, timeout=30) as response:
                    status = getattr(response, 'status', 200)
                    if offset and status == 206:
                        content_range = response.headers.get('Content-Range', '')
                        if not content_range.startswith(f'bytes {offset}-'):
                            raise ValueError('Сервер вернул неверный диапазон загрузки')
                        mode = 'ab'
                    else:
                        mode = 'wb'
                        digest = hashlib.sha256()
                    with temporary.open(mode) as target:
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
            if isinstance(exc, ValueError) or getattr(exc, 'code', None) == 416:
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
        failed_tasks = set()
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                diagnostics.log_error('model_download', type(exc), exc.__traceback__)
                if futures[future]['task'] is not None and not cancelled.is_set():
                    failed_tasks.add(futures[future]['task'])
                    continue
                cancelled.set()
                raise
    if failed_tasks:
        if failed_tasks & {'nvidia', 'turbo'}:
            failed_tasks.update({'nvidia', 'turbo'})
        for package in needed:
            if package['task'] in failed_tasks:
                (output / package['name']).unlink(missing_ok=True)
        updates.put(('warning', 'Не удалось загрузить некоторые дополнительные компоненты: ' + ', '.join(sorted(failed_tasks)) + '. Базовые модели будут установлены. Запустите установщик повторно, чтобы скачать недостающие компоненты.'))


def install_downloads(target, output, tasks, cancelled, updates):
    """Install downloaded, verified components after setup has completed."""
    packages = json.loads(CONFIG.read_text(encoding='utf-8'))
    marker = target / 'data' / '.models-installing'
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    for package in packages:
        if package['task'] is not None and package['task'] not in tasks:
            continue
        source = output / package['name']
        if not source.is_file():
            continue  # Already installed, or an optional GPU download failed.
        if cancelled.is_set():
            raise InterruptedError('Подготовка отменена')
        expected = package['files'][0]['sha256'] if package.get('archive_member') else package['sha256']
        if file_digest(source, cancelled) != expected:
            raise ValueError(f"Не совпала контрольная сумма: {package['name']}")
        updates.put(('status', 'Устанавливаем модели…'))
        if package['name'].endswith('.zip'):
            base = target / ('_internal' if package['task'] == 'nvidia' else 'data')
            base.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(source) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    destination = (base / member.filename).resolve()
                    if not destination.is_relative_to(base.resolve()):
                        raise ValueError('Небезопасный путь в архиве модели')
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as src, tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as dst:
                        temp = Path(dst.name)
                        try:
                            while data := src.read(CHUNK):
                                if cancelled.is_set(): raise InterruptedError('Подготовка отменена')
                                dst.write(data)
                        except BaseException:
                            dst.close(); temp.unlink(missing_ok=True)
                            raise
                    temp.replace(destination)
        else:
            destination = target / package['files'][0]['path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)
        source.unlink(missing_ok=True)
    marker.unlink(missing_ok=True)
    if output.resolve() == (target / '.model-downloads').resolve():
        shutil.rmtree(output, ignore_errors=True)


def main():
    if len(sys.argv) == 6 and sys.argv[1] == '--hf-worker':
        from huggingface_hub import hf_hub_download
        hf_hub_download(repo_id=sys.argv[2], filename=sys.argv[3], revision=sys.argv[4], local_dir=sys.argv[5])
        return 0
    from single_instance import SingleInstance
    guard = SingleInstance(r'Local\LiveTranslate.ModelsDownload.1')
    if not guard.is_primary:
        guard.close()
        return 1
    try:
        return run_setup()
    finally:
        guard.close()


def run_setup():
    try:
        diagnostics.configure()
    except OSError:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tasks', default='')
    parser.add_argument('--silent', action='store_true')
    parser.add_argument('--auto-gpu', action='store_true')
    parser.add_argument('--install', action='store_true')
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
            if args.install: install_downloads(args.target, args.output, tasks, cancelled, updates)
            warnings = []
            while not updates.empty():
                kind, value = updates.get()
                if kind == 'warning': warnings.append(value)
            if warnings:
                warning_file = args.target / 'data' / 'install-warnings.log'
                warning_file.parent.mkdir(parents=True, exist_ok=True)
                warning_file.write_text('\n'.join(warnings), encoding='utf-8')
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
    root.geometry('500x195')
    root.attributes('-topmost', True)
    root.after(1000, lambda: root.attributes('-topmost', False))
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    title = ttk.Label(frame, text='Подготовка LiveTranslate', font=('Segoe UI', 13, 'bold'))
    title.pack(anchor='w')
    status = tk.StringVar(value='Проверяем компоненты…')
    ttk.Label(frame, textvariable=status).pack(anchor='w', pady=(12, 4))
    progress = ttk.Progressbar(frame, mode='indeterminate')
    progress.pack(fill='x', pady=(2, 4))
    progress.start(15)
    detail = tk.StringVar(value='')
    ttk.Label(frame, textvariable=detail).pack(anchor='w')
    cancel_button = ttk.Button(frame, text='Отмена', command=cancelled.set)
    cancel_button.pack(anchor='e', pady=(6, 0))
    root.protocol('WM_DELETE_WINDOW', cancelled.set)
    state = {'result': None, 'bytes': 0}
    def run():
        try:
            prepare(args.target, args.output, tasks, cancelled, updates)
            if args.install: install_downloads(args.target, args.output, tasks, cancelled, updates)
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
            elif kind == 'warning': messagebox.showwarning('Загрузка компонентов', value, parent=root)
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
