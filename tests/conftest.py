"""Group existing unittest tests without changing their execution semantics."""
import pytest
import gc


@pytest.fixture(autouse=True)
def collect_tk_objects_on_main_thread(request):
    """Dispose abandoned Tk cycles before another test starts background workers."""
    yield
    if request.node.get_closest_marker('gui'):
        gc.collect()


def pytest_collection_modifyitems(items):
    gui = {'test_note_mouse.py', 'test_app_library.py', 'test_local_translator.py'}
    audio = {'test_capture.py', 'test_whisper_stream.py', 'test_speaker_diarization.py'}
    for item in items:
        filename = item.path.name
        if filename in gui:
            item.add_marker(pytest.mark.gui)
        if filename in audio:
            item.add_marker(pytest.mark.audio)
        if filename == 'test_local_translator.py' and 'local_model' in item.name:
            item.add_marker(pytest.mark.model)
