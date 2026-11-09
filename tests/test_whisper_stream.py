from types import SimpleNamespace
import unittest
import threading
from unittest.mock import Mock

import numpy as np
from whisper_stream import RATE, WhisperStream, normalize_terms


def segment(text, words):
    return SimpleNamespace(text=text, words=[SimpleNamespace(start=s, end=e, word=w) for s, e, w in words],
                           compression_ratio=1, avg_logprob=-0.25, no_speech_prob=0.05)


class StreamTests(unittest.TestCase):
    def test_technical_names(self):
        self.assertEqual(normalize_terms("доступ по ССН к позгресса и инжинкса"),
                         "доступ по SSH к PostgreSQL и Nginx")
        self.assertEqual(normalize_terms("один два три"), "один два три")
        self.assertEqual(normalize_terms("доступ по ССС к серверу"), "доступ по SSH к серверу")
    def setUp(self):
        self.lines = []
        self.partials = []
        self.model = Mock()
        self.translation = Mock()
        self.translation.translate.side_effect = lambda text: text
        self.stream = WhisperStream(self.model, {"en": self.translation}, None, None,
                                    lambda *args: self.lines.append(args), self.partials.append)

    def test_silence_hum_and_stationary_noise_never_reach_whisper(self):
        t = np.arange(15 * RATE) / RATE
        noise = np.random.default_rng(222).normal(0, 0.008, t.size)
        for signal in (np.zeros_like(t), 0.015 * np.sin(2 * np.pi * 50 * t), noise):
            pcm = (signal * 32767).astype("<i2").tobytes()
            for i in range(0, len(pcm), 3200):
                self.stream.accept(pcm[i:i + 3200])
            self.stream.flush()
        self.model.detect_language.assert_not_called()
        self.assertEqual((self.lines, self.partials), ([], []))

    def test_long_sentence_is_translated_once_with_unfinished_tail(self):
        self.model.detect_language.return_value = ("en", 0.99, [])
        self.model.transcribe.side_effect = [
            ([segment("We need to hear the rest", [(0, 8, "We need"), (10, 19, " to hear"),
                                                    (21.5, 23, " the rest")])], None),
            ([segment("the rest of this sentence.", [(0, 2.5, " the rest"), (4, 6, " of this sentence.")])], None)]
        self.stream.frames.extend(bytes(24 * RATE * 2))
        self.stream.voiced = 50
        self.stream.finish(final=False)
        self.assertFalse(self.lines)
        self.assertEqual(self.stream.unfinished, "We need to hear")
        self.assertGreater(len(self.stream.frames), RATE * 2)
        self.stream.frames.extend(bytes(3 * RATE * 2))
        self.stream.flush()
        self.translation.translate.assert_called_once_with("We need to hear the rest of this sentence.")
        self.assertEqual(self.model.transcribe.call_args.kwargs["initial_prompt"], "We need to hear")

    def test_repeated_digits_are_rejected_but_spoken_number_is_kept(self):
        digits = "1-2-3-" + "4-" * 40
        for text, expected in [(digits, 0), ("Four.", 1)]:
            self.model.detect_language.return_value = ("en", 0.96, [])
            self.model.transcribe.return_value = ([segment(text, [(0, 1, text)])], None)
            self.stream.frames.extend(bytes(RATE * 2))
            self.stream.voiced = 20
            self.stream.flush()
            self.assertEqual(len(self.lines), expected)

    def test_late_preview_cannot_reappear_after_finalization(self):
        started, release = threading.Event(), threading.Event()
        preview = []
        def slow_transcribe(*args, **kwargs):
            started.set()
            release.wait(3)
            return [segment("Hello.", [(0, 1, "Hello.")])], SimpleNamespace(language="en", language_probability=0.9)
        self.model.transcribe.side_effect = slow_transcribe
        stream = WhisperStream(self.model, {"en": self.translation}, None, None, lambda *x: None,
                               lambda x: None, preview.append)
        stream.frames.extend(bytes(3 * RATE * 2))
        stream.clock = 3 * RATE
        stream.queue_preview()
        self.assertTrue(started.wait(2))
        stream.clear_preview()
        release.set()
        stream.close()
        self.assertTrue(all(value is None for value in preview))
