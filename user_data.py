"""User files in Documents, with non-destructive migration from older releases."""
from contextlib import closing
import ctypes
import hashlib
import os
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path


def documents_dir():
    override = os.environ.get('LIVETRANSLATE_DOCUMENTS')
    if override:
        return Path(override)
    if os.name != 'nt':
        return Path.home() / 'Documents'
    folder_id = uuid.UUID('fdd39ad0-238f-46af-adb4-6c85480369c7')
    guid = (ctypes.c_ubyte * 16).from_buffer_copy(folder_id.bytes_le)
    result = ctypes.c_void_p()
    shell = ctypes.windll.shell32
    shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    status = shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(result))
    if status != 0:
        raise OSError(f'Не удалось определить папку «Документы» (код {status}).')
    try:
        return Path(ctypes.wstring_at(result.value))
    finally:
        free = ctypes.windll.ole32.CoTaskMemFree
        free.argtypes = [ctypes.c_void_p]
        free(result)


def data_directory():
    return documents_dir() / 'LiveTranslate'


def legacy_directory():
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'LiveTranslate'


def migrate_user_data():
    dest = data_directory()
    old = legacy_directory()
    dest.mkdir(parents=True, exist_ok=True)
    marker = dest / '.migration-from-appdata-complete'
    if marker.exists():
        return dest
    source_db, target_db = old / 'library.sqlite3', dest / 'library.sqlite3'
    if source_db.is_file() and not target_db.exists():
        # SQLite backup includes committed WAL data and never overwrites an existing library.
        temp = dest / 'library.migrating.sqlite3'
        if temp.exists():
            raise FileExistsError(f'Обнаружена незавершённая копия базы: {temp}')
        try:
            with closing(sqlite3.connect(f'{source_db.as_uri()}?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(temp)) as target:
                    source.backup(target)
            # Windows rename fails if the destination exists; it never overwrites a library.
            if os.name == 'nt':
                os.rename(temp, target_db)
            else:
                os.link(temp, target_db)
        finally:
            temp.unlink(missing_ok=True)
    old_recordings = old / 'Recordings'
    if old_recordings.is_dir() and old_recordings.resolve() != (dest / 'Recordings').resolve():
        for item in old_recordings.rglob('*'):
            if not item.is_file():
                continue
            target = dest / 'Recordings' / item.relative_to(old_recordings)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                with item.open('rb') as source:
                    source_hash = hashlib.file_digest(source, 'sha256').hexdigest()
                with target.open('rb') as existing:
                    if hashlib.file_digest(existing, 'sha256').hexdigest() == source_hash:
                        continue
                target = target.with_name(f'{target.stem}.legacy-{source_hash}{target.suffix}')
                if target.exists():
                    with target.open('rb') as existing:
                        if hashlib.file_digest(existing, 'sha256').hexdigest() == source_hash:
                            continue
                    raise FileExistsError(f'Не удалось сохранить копию записи: {target}')
            temporary = None
            try:
                with item.open('rb') as source, tempfile.NamedTemporaryFile(dir=target.parent, prefix='.migration-', delete=False) as output:
                    temporary = Path(output.name)
                    shutil.copyfileobj(source, output)
                if os.name == 'nt':
                    os.rename(temporary, target)
                else:
                    os.link(temporary, target)
            except FileExistsError:
                pass
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    if source_db.exists() or old_recordings.is_dir():
        marker.touch(exist_ok=True)
    return dest
