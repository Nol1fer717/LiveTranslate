from types import SimpleNamespace
import unittest
import threading
from unittest.mock import Mock, patch

import numpy as np
from whisper_stream import RATE, WhisperStream, StableWords, normalize_terms, remove_phantom_outro


def segment(text, words):
    return SimpleNamespace(text=text, words=[SimpleNamespace(start=s, end=e, word=w) for s, e, w in words],
                           compression_ratio=1, avg_logprob=-0.25, no_speech_prob=0.05)


class StreamTests(unittest.TestCase):
    def test_stable_words_are_never_replaced(self):
        s=StableWords()
        self.assertEqual(s.update('Hello wor'), '')
        self.assertEqual(s.update('Hello world'), 'Hello')
        self.assertEqual(s.update('Hello world again'), 'Hello world')
        self.assertEqual(s.update('Yellow world again'), 'Hello world')
        self.assertEqual(s.update('Hello world again'), 'Hello world')
        self.assertEqual(s.update('Hello world again'), 'Hello world again')

    def test_final_output_preserves_already_shown_words(self):
        self.stream.preview = lambda value: None
        self.stream.stable_words.update('hello there')
        self.stream.stable_words.update('hello there')
        self.model.detect_language.return_value = ('en', .99, [])
        self.model.transcribe.return_value = ([segment('yellow there friend', [(0,.3,'yellow'),(.3,.6,' there'),(.6,1,' friend')])], None)
        self.stream.frames.extend(bytes(RATE*2)); self.stream.voiced=20
        self.stream.finish(final=True)
        self.assertEqual(self.lines[0][0], 'hello there friend')

    def test_segmentation_scale_controls_pause(self):
        def interval(level):
            s=WhisperStream(self.model, {'en':self.translation}, None, None, lambda *a:None, lambda *a:None, split_level=level)
            return s.quiet_frames
        self.assertLess(interval(1), interval(5))
        self.assertLess(interval(5), interval(10))
        with self.assertRaises(ValueError): interval(0)

    def test_preview_shows_original_without_translation(self):
        received=threading.Event(); values=[]
        self.model.transcribe.return_value=([segment('Hello there.', [(0,1,'Hello there.')])], SimpleNamespace(language='en',language_probability=.99))
        def preview(value):
            if value: values.append(value); received.set()
        stream=WhisperStream(self.model, {'en':self.translation}, None, None, lambda *a:None, lambda *a:None, preview)
        try:
            stream.frames.extend(bytes(2*RATE*2));stream.clock=2*RATE;stream.queue_preview()
            deadline=threading.Event()
            for _ in range(15):
                if stream.stable_words.previous: break
                deadline.wait(.02)
            stream.clock+=RATE;stream.queue_preview()
            self.assertTrue(received.wait(3));self.assertEqual(values[-1],('Hello there','','EN'))
            self.translation.translate.assert_not_called()
        finally:
            stream.close()

    def test_suppresses_phantom_outro_without_removing_normal_sentences(self):
        self.assertEqual(remove_phantom_outro('Продолжение следует...'), '')
        self.assertEqual(remove_phantom_outro('Привет. Продолжение следует.'), 'Привет.')
        self.assertEqual(remove_phantom_outro('Hello. To be continued.'), 'Hello.')
        self.assertEqual(remove_phantom_outro('Вот что это за продолжение следует?'), 'Вот что это за продолжение следует?')
        self.stream.publish('Продолжение следует.', 'en', None)
        self.assertFalse(self.lines)

    def test_suppresses_standalone_subtitle_credit(self):
        self.assertEqual(remove_phantom_outro('Субтитры сделал DimaTorZok'), '')
        self.assertEqual(remove_phantom_outro('Subtitles made by DimaTorZok.'), '')
        self.assertEqual(remove_phantom_outro('Привет. Субтитры сделал DimaTorZok.'), 'Привет.')
        self.assertEqual(remove_phantom_outro('Я знаю кто сделал субтитры.'), 'Я знаю кто сделал субтитры.')

    def test_missing_german_model_reports_how_to_install_it(self):
        self.stream.publish("Guten Tag.", "de", None)
        self.assertEqual(self.lines[0][0], "Guten Tag.")
        self.assertIn("установщик", self.lines[0][1])
        self.assertEqual(self.lines[0][3], "DE → RU")

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

    def test_unknown_speakers_do_not_share_recognition_context(self):
        self.stream.speaker_decoder = Mock()
        self.stream.speaker_decoder.FinalResult.return_value = '{}'
        self.stream.speakers = Mock()
        self.stream.speakers.label.return_value = 'Голос не определён'
        self.model.detect_language.return_value = ('en', 0.99, [])
        self.model.transcribe.return_value = ([segment('Hello.', [(0, 1, 'Hello.')])], None)
        for _ in range(2):
            self.stream.frames.extend(bytes(RATE * 2))
            self.stream.voiced = 20
            self.stream.finish(final=True)
        self.assertEqual(len(self.lines), 2)
        self.assertIsNone(self.model.transcribe.call_args.kwargs['initial_prompt'])
        self.assertNotIn('hotwords', self.model.transcribe.call_args.kwargs)

    def test_tail_recognition_discards_words_from_padding(self):
        self.model.detect_language.return_value = ('en', 0.99, [])
        self.model.transcribe.side_effect = [
            ([segment('Hello', [(0, 1, 'Hello')])], None),
            ([segment(' world hallucination', [(0.2, 0.5, ' world'), (1.1, 1.4, ' hallucination')])], None),
        ]
        self.stream.frames.extend(bytes(2 * RATE * 2))
        self.stream.voiced = 20
        with patch('whisper_stream.get_speech_timestamps', return_value=[{'start': 0, 'end': RATE}]):
            self.stream.finish(final=True)
        self.assertEqual(self.lines[0][0], 'Hello world')

    def test_speaker_turns_split_words_and_keep_overlap_unknown(self):
        self.stream.diarizer = Mock()
        self.stream.diarizer.turns.return_value = [(0, 1, 'Голос 1'), (1, 2, 'Голос 2'), (1.5, 2, 'Голос 1')]
        self.model.detect_language.return_value = ('en', 0.99, [])
        self.model.transcribe.return_value = ([segment('Hello there both', [(0.1, 0.6, 'Hello'), (1.05, 1.3, ' there'), (1.6, 1.9, ' both')])], None)
        self.stream.frames.extend(bytes(2 * RATE * 2)); self.stream.voiced = 20
        self.stream.finish(final=True)
        self.assertEqual([(x[0], x[2]) for x in self.lines], [('Hello', 'Голос 1'), ('there both', 'Голос не определён')])

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
