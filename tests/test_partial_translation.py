import threading
import unittest
from unittest.mock import Mock

from partial_translation import PartialTranslator


class PartialTranslationTests(unittest.TestCase):
    def test_nonfinal_reset_reuses_previous_stable_prefix(self):
        ready=threading.Event(); values=[]; model=Mock()
        model.translate.side_effect=lambda text: text.upper()
        def publish(value): values.append(value); ready.set()
        worker=PartialTranslator({'en':model},publish)
        try:
            worker.submit('hello there','en'); self.assertTrue(ready.wait(2)); ready.clear()
            worker.reset(); worker.submit('hello there','en'); self.assertTrue(ready.wait(2)); ready.clear()
            worker.submit('hello there friend','en'); self.assertTrue(ready.wait(2))
            self.assertEqual([call.args[0] for call in model.translate.call_args_list], ['hello there','friend'])
            self.assertEqual(values[-1][1], 'HELLO THERE FRIEND')
        finally: worker.close()
    def test_changed_last_word_is_translated_again(self):
        ready=threading.Event(); results=[]; model=Mock()
        model.translate.side_effect=lambda text: text.upper()
        def publish(value): results.append(value); ready.set()
        worker=PartialTranslator({'en':model}, publish)
        try:
            worker.submit('I need a note', 'en'); self.assertTrue(ready.wait(2)); ready.clear()
            worker.submit('I need a notebook', 'en'); self.assertTrue(ready.wait(2))
            self.assertEqual(results[-1][1], 'I NEED A NOTEBOOK')
        finally: worker.close()
    def test_translates_only_new_words_and_avoids_repeated_requests(self):
        ready = threading.Event(); results = []
        model = Mock()
        model.translate.side_effect = lambda text: text.upper()
        def publish(value):
            results.append(value); ready.set()
        worker = PartialTranslator({'en': model}, publish)
        try:
            worker.submit('hello there', 'en'); self.assertTrue(ready.wait(2)); ready.clear()
            worker.submit('hello there', 'en')
            worker.submit('hello there friend', 'en'); self.assertTrue(ready.wait(2))
            self.assertEqual(results[-1], ('hello there friend', 'HELLO THERE FRIEND', 'EN'))
            self.assertEqual([call.args[0] for call in model.translate.call_args_list], ['hello there', 'friend'])
        finally:
            worker.close()

    def test_translation_error_publishes_unavailable_marker(self):
        ready = threading.Event(); results = []
        model = Mock()
        model.translate.side_effect = RuntimeError('translation failed')
        worker = PartialTranslator({'en': model}, lambda value: (results.append(value), ready.set()))
        try:
            worker.submit('hello', 'en')
            self.assertTrue(ready.wait(2))
            self.assertEqual(results[-1][:2], ('hello', 'Предварительный перевод недоступен'))
        finally:
            worker.close()

    def test_discard_result_after_reset(self):
        started = threading.Event(); release = threading.Event(); finished = threading.Event(); results = []
        def translate(text):
            started.set(); release.wait(2); finished.set(); return 'late'
        worker = PartialTranslator({'en': Mock(translate=translate)}, results.append)
        try:
            worker.submit('old words', 'en'); self.assertTrue(started.wait(2))
            worker.reset(); release.set(); self.assertTrue(finished.wait(2))
            worker.thread.join(.05)
            self.assertEqual(results, [])
        finally:
            release.set(); worker.close()
