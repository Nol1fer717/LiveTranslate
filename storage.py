"""Local persistence for translation sessions and personal notes."""
import sqlite3
from datetime import datetime
from pathlib import Path
from user_data import data_directory, legacy_directory, migrate_user_data


def timestamp():
    return datetime.now().isoformat(timespec='seconds')


class Storage:
    def __init__(self, path=None):
        self.legacy_conflict = False
        self.migration_warnings = []
        if path is None:
            destination = data_directory()
            self.legacy_conflict = ((destination / 'library.sqlite3').exists()
                                    and (legacy_directory() / 'library.sqlite3').exists()
                                    and not (destination / '.migration-library-complete').exists()
                                    and not (destination / '.migration-from-appdata-complete').exists())
            self.path = migrate_user_data(self.migration_warnings) / 'library.sqlite3'
        else:
            self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.create_collation('UNICODE_CASEFOLD', lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
        self.db.execute('PRAGMA foreign_keys = ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY, started TEXT NOT NULL, ended TEXT, mode TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS phrases (id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, time TEXT, source_index INTEGER, speaker TEXT, source_lang TEXT, target_lang TEXT, source TEXT, target TEXT);
        CREATE TABLE IF NOT EXISTS folders (id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE);
        CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL, title TEXT NOT NULL, body TEXT NOT NULL, updated TEXT NOT NULL);
        ''')
        self.db.commit()

    def start_session(self, mode):
        with self.db:
            return self.db.execute('INSERT INTO sessions(started, mode) VALUES (?, ?)', (timestamp(), mode)).lastrowid

    def add_phrase(self, session, entry):
        with self.db:
            self.db.execute('INSERT INTO phrases(session_id,time,source_index,speaker,source_lang,target_lang,source,target) VALUES (?,?,?,?,?,?,?,?)',
                            (session, entry['time'], entry['index'], entry['speaker'], entry['from'], entry['to'], entry['source'], entry['target']))

    def end_session(self, session):
        with self.db:
            self.db.execute('UPDATE sessions SET ended=? WHERE id=?', (timestamp(), session))

    def sessions(self):
        return self.db.execute('SELECT s.id,s.started,s.ended,s.mode,COUNT(p.id) FROM sessions s LEFT JOIN phrases p ON p.session_id=s.id GROUP BY s.id ORDER BY s.id DESC').fetchall()

    def phrases(self, session):
        return self.db.execute('SELECT time,source_index,speaker,source_lang,target_lang,source,target FROM phrases WHERE session_id=? ORDER BY id', (session,)).fetchall()

    def delete_session(self, session):
        with self.db:
            self.db.execute('DELETE FROM sessions WHERE id=?', (session,))

    def folders(self):
        return self.db.execute('SELECT id,name FROM folders ORDER BY name COLLATE UNICODE_CASEFOLD').fetchall()

    def add_folder(self, name):
        with self.db:
            if self.db.execute('SELECT 1 FROM folders WHERE name = ? COLLATE UNICODE_CASEFOLD', (name,)).fetchone():
                raise sqlite3.IntegrityError('Folder name already exists')
            return self.db.execute('INSERT INTO folders(name) VALUES (?)', (name,)).lastrowid

    def rename_folder(self, folder, name):
        with self.db:
            if self.db.execute('SELECT 1 FROM folders WHERE id != ? AND name = ? COLLATE UNICODE_CASEFOLD', (folder, name)).fetchone():
                raise sqlite3.IntegrityError('Folder name already exists')
            self.db.execute('UPDATE folders SET name=? WHERE id=?', (name, folder))

    def delete_folder(self, folder):
        with self.db:
            self.db.execute('DELETE FROM folders WHERE id=?', (folder,))

    def notes(self, folder, sort):
        order = 'title COLLATE UNICODE_CASEFOLD, id DESC' if sort == 'По названию' else 'updated DESC, id DESC'
        if folder == 'all':
            return self.db.execute(f'SELECT id,title,updated,folder_id FROM notes ORDER BY {order}').fetchall()
        if folder is None:
            return self.db.execute(f'SELECT id,title,updated,folder_id FROM notes WHERE folder_id IS NULL ORDER BY {order}').fetchall()
        return self.db.execute(f'SELECT id,title,updated,folder_id FROM notes WHERE folder_id=? ORDER BY {order}', (folder,)).fetchall()

    def note(self, note):
        return self.db.execute('SELECT title,body,folder_id FROM notes WHERE id=?', (note,)).fetchone()

    def add_note(self, folder):
        with self.db:
            return self.db.execute('INSERT INTO notes(folder_id,title,body,updated) VALUES (?,?,?,?)', (folder, 'Новая заметка', '', timestamp())).lastrowid

    def save_note(self, note, title, body, folder):
        with self.db:
            self.db.execute('UPDATE notes SET title=?,body=?,folder_id=?,updated=? WHERE id=?', (title or 'Без названия', body, folder, timestamp(), note))

    def delete_note(self, note):
        with self.db:
            self.db.execute('DELETE FROM notes WHERE id=?', (note,))

    def close(self):
        self.db.close()
