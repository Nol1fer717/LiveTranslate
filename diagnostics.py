"""Local diagnostics that omit exception messages, locals and transcript text."""
import logging
from logging.handlers import RotatingFileHandler
import os
import platform
from pathlib import Path
import sys
import threading
import traceback


def log_directory():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'LiveTranslate' / 'logs'


def configure(root=None):
    directory = log_directory()
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('livetranslate')
    shutdown()
    handler = RotatingFileHandler(directory / 'application.log', maxBytes=5 * 1024 * 1024,
                                  backupCount=4, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info('Запуск: версия=%s ОС=%s Python=%s', '1.5.1', platform.system(), platform.python_version())
    def main_hook(kind, value, tb):
        log_error('main', kind, tb)
    def thread_hook(args):
        log_error('worker', args.exc_type, args.exc_traceback)
    sys.excepthook = main_hook
    threading.excepthook = thread_hook
    if root is not None:
        root.report_callback_exception = lambda kind, value, tb: log_error('tk', kind, tb)
    return directory


def shutdown():
    logger = logging.getLogger('livetranslate')
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def log_error(stage, kind, tb):
    # Do not log exception messages, code source lines, local variables or full paths:
    # any of them can contain speech, filenames or other private data.
    frames = traceback.extract_tb(tb) if tb else []
    safe = ' > '.join(f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}' for frame in frames)
    logger = logging.getLogger('livetranslate')
    logger.error('Этап=%s тип=%s стек=%s', stage, kind.__name__, safe)
    if stage in ('main', 'worker', 'session'):
        try:
            (log_directory() / '.last-crash').touch()
        except OSError:
            pass


def set_level(detailed):
    logging.getLogger('livetranslate').setLevel(logging.DEBUG if detailed else logging.INFO)


def record_model(model, device):
    safe_model = model if model in ('Small', 'Turbo') else 'unknown'
    safe_device = device if device in ('cpu', 'cuda') else 'unknown'
    logging.getLogger('livetranslate').info('Модель=%s устройство=%s', safe_model, safe_device)


def record_timing(stage, seconds):
    if stage in ('partial_translation', 'final_translation'):
        logging.getLogger('livetranslate').debug('Этап=%s длительность=%.3f с', stage, seconds)


def record_vad_summary(frames, peak, below_threshold):
    """Log aggregate detection statistics without audio, text or device identifiers."""
    logging.getLogger('livetranslate').debug(
        'VAD кадров=%d максимум=%.3f ниже_порога=%d причина=низкая_вероятность',
        frames, peak, below_threshold)


def consume_crash_notice():
    marker = log_directory() / '.last-crash'
    try:
        if marker.exists():
            marker.unlink()
            return True
    except OSError:
        pass
    return False
