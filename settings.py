"""Persistent user preferences for speech segmentation."""
import json
import os
import tempfile
from pathlib import Path

DEFAULT_SPLIT = 5


def read_split_level(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8')).get('split_level', DEFAULT_SPLIT)
        if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 10:
            return value
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return DEFAULT_SPLIT


def save_split_level(path, value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10:
        raise ValueError('Скорость разбиения должна быть от 1 до 10')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'split_level': value}, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
