"""Check complete base model manifests without reading large model files on UI ticks."""
import json
import hashlib
import os
import sys
from pathlib import Path

_verified_stale_markers = {}


def downloader_running():
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenMutexW(0x00100000, False, r'Local\LiveTranslate.ModelsDownload.1')
    if handle:
        kernel.CloseHandle(handle)
        return True
    return False if ctypes.get_last_error() == 2 else None


def required_files(data, manifest=None):
    packages = json.loads(Path(manifest or manifest_path()).read_text(encoding='utf-8'))
    root = Path(data).parent
    return [(root / entry['path'], entry.get('sha256')) for package in packages
            if package['task'] is None for entry in package['files']]


def fingerprint(marker, files):
    m = marker.stat()
    return (m.st_mtime_ns, m.st_size, tuple((p.stat().st_mtime_ns, p.stat().st_size) for p, _ in files))


def recover_stale_marker(data, manifest=None):
    """Verify stale installation contents off the UI thread; never modify program files."""
    data = Path(data); marker = data / '.models-installing'
    if not marker.exists() or downloader_running() is not False:
        return None
    try:
        files = required_files(data, manifest)
        if not files:
            return False
        before = fingerprint(marker, files)
        for path, expected in files:
            if not expected:
                return False
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                while block := stream.read(1024 * 1024):
                    digest.update(block)
            if digest.hexdigest() != expected:
                return False
        if downloader_running() is not False or fingerprint(marker, files) != before:
            return None
        _verified_stale_markers[str(data.resolve())] = before
        return True
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        return False

def manifest_path():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'packages.json'
    return Path(__file__).resolve().parent / 'installer' / 'packages.json'


def base_models_ready(data, manifest=None):
    data = Path(data)
    try:
        files = required_files(data, manifest)
        if not files:
            return False
        marker = data / '.models-installing'
        if marker.exists():
            cached = _verified_stale_markers.get(str(data.resolve()))
            return bool(cached and downloader_running() is False and fingerprint(marker, files) == cached)
        return all(path.is_file() for path, _ in files)
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        return False
