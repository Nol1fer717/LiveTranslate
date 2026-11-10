from types import SimpleNamespace
import unittest
import threading
import time
from unittest.mock import Mock, patch

import numpy as np
from whisper_stream import RATE, WhisperStream, StableWords, normalize_terms, remove_phantom_outro


def segment(text, words):
    return SimpleNamespace(text=text, words=[SimpleNamespace(start=s, end=e, word=w) for s, e, w in words],
                           compression_ratio=1, avg_logprob=-0.25, no_speech_prob=0.05)


class StreamTests(unittest.TestCase):
    def test_quiet_short_phrase_does_not_commit_invented_preview_words(self):
        self.stream.quiet_mode = True
        self.stream.preview = lambda value: None
        self.stream.stable_words.update('Hello no'); self.stream.stable_words.update('Hello no')
        self.model.detect_language.return_value = ('en', .99, [])
        self.model.transcribe.return_value = ([segment('Hello.', [(0, .4, 'Hello.')])], None)
        self.stream.frames.extend(bytes(2 * RATE * 2)); self.stream.voiced = 20
        self.stream.previous_text='old context'; self.stream.previous_language='en'
        with patch('whisper_stream.get_speech_timestamps', return_value=[]):
            self.stream.finish(final=True)
        self.assertEqual([line[0] for line in self.lines], ['Hello.'])
        self.assertIsNone(self.model.transcribe.call_args.kwargs['initial_prompt'])

    def test_quiet_short_phrase_does_not_decode_tail_as_extra_speech(self):
        self.stream.quiet_mode = True
        self.model.detect_language.return_value = ('en', .99, [])
        self.model.transcribe.side_effect = [([segment('Hello.', [(0, .4, 'Hello.')])], None),
                                             ([segment('No.', [(0, .2, ' No.')])], None)]
        self.stream.frames.extend(bytes(2 * RATE * 2)); self.stream.voiced = 20
        with patch('whisper_stream.get_speech_timestamps', return_value=[{'start': 0, 'end': 8000}]):
            self.stream.finish(final=True)
        self.assertEqual([line[0] for line in self.lines], ['Hello.'])
        self.assertEqual(self.model.transcribe.call_count, 1)

    def test_ten_minutes_of_weak_hum_and_noise_do_not_trigger_speech(self):
        for kind in ('silence', 'hum', 'noise'):
            with self.subTest(kind=kind):
                self.model.reset_mock()
                stream=WhisperStream(self.model, {}, None, None, lambda *a:None, lambda *a:None)
                rng=np.random.default_rng(153); sample=0
                for _ in range(600):
                    if kind == 'silence':
                        audio=np.zeros(RATE)
                    elif kind == 'hum':
                        audio=.004*np.sin(2*np.pi*50*np.arange(sample, sample+RATE)/RATE); sample+=RATE
                    else:
                        audio=rng.normal(0, .004, RATE)
                    stream.accept((audio*32767).astype('<i2').tobytes())
                stream.flush(); stream.close()
                self.model.detect_language.assert_not_called()

    def test_tail_redecode_does_not_repeat_same_word_at_boundary(self):
        self.model.detect_language.return_value = ('en', .99, [])
        self.model.transcribe.side_effect = [([segment('Hello!', [(0, .4, 'Hello!')])], None),
                                             ([segment('Hello!', [(0, .18, 'Hello!')])], None)]
        self.stream.frames.extend(bytes(2 * RATE * 2)); self.stream.voiced = 20
        with patch('whisper_stream.get_speech_timestamps', return_value=[{'start': 0, 'end': 8000}]):
            self.stream.finish(final=True)
        self.assertEqual([line[0] for line in self.lines], ['Hello!'])

    def test_tail_overlap_matches_committed_word_with_leading_space(self):
        self.stream.preview = lambda value: None
        self.stream.stable_words.update('Hello'); self.stream.stable_words.update('Hello')
        self.model.detect_language.return_value = ('en', .99, [])
        self.model.transcribe.side_effect = [([segment('Hello!', [(0, .4, ' Hello!')])], None),
                                             ([segment('Hello!', [(0, .18, ' Hello!')])], None)]
        self.stream.frames.extend(bytes(2 * RATE * 2)); self.stream.voiced = 20
        with patch('whisper_stream.get_speech_timestamps', return_value=[{'start': 0, 'end': 8000}]):
            self.stream.finish(final=True)
        self.assertEqual([line[0] for line in self.lines], ['Hello'])

    def test_tail_keeps_deliberately_repeated_word_after_pause(self):
        self.model.detect_language.return_value = ('en', .99, [])
        self.model.transcribe.side_effect = [([segment('Hello', [(0, .4, 'Hello')])], None),
                                             ([segment('hello', [(.5, .8, ' hello')])], None)]
        self.stream.frames.extend(bytes(2 * RATE * 2)); self.stream.voiced = 20
        with patch('whisper_stream.get_speech_timestamps', return_value=[{'start': 8000, 'end': 12800}]):
            self.stream.finish(final=True)
        self.assertEqual([line[0] for line in self.lines], ['Hello hello'])
    def test_quiet_profile_detects_low_probability_speech(self):
        self.stream.quiet_mode = True
        self.stream.gate.probability = Mock(return_value=.1)
        self.stream.accept(bytes(512 * 2 * 8))
        self.assertGreaterEqual(self.stream.voiced, 6)
        self.assertTrue(self.stream.frames)

    def test_normal_profile_rejects_low_probability_speech(self):
        self.stream.gate.probability = Mock(return_value=.1)
        self.stream.accept(bytes(512 * 2 * 8))
        self.assertFalse(self.stream.frames)

    def test_preview_does_not_repeat_overlap_from_previous_window(self):
        received=threading.Event(); values=[]
        self.model.transcribe.return_value=([segment('there friend', [(0,.4,'there'),(.4,.8,' friend')])], SimpleNamespace(language='en',language_probability=.99))
        def preview(value):
            if value:
                values.append(value)
                if value[0].endswith('friend'): received.set()
        stream=WhisperStream(self.model, {'en':self.translation}, None, None, lambda *a:None, lambda *a:None, preview)
        try:
            stream.unfinished='hello there'; stream.pending_preview_overlap=['there']
            stream.frames.extend(bytes(2*RATE*2)); stream.clock=2*RATE; stream.queue_preview()
            deadline=time.monotonic()+3
            while not stream.stable_words.previous and time.monotonic()<deadline: time.sleep(.01)
            stream.clock+=RATE; stream.queue_preview()
            self.assertTrue(received.wait(3))
            self.assertTrue(all('there there' not in value[0] for value in values))
            self.assertEqual(values[-1][0], 'hello there friend')
        finally: stream.close()
    def test_nonfinal_preview_overlap_is_not_duplicated(self):
        self.stream.preview=lambda value: None
        self.stream.stable_words.update('hello there'); self.stream.stable_words.update('hello there')
        self.model.detect_language.return_value=('en', .99, [])
        self.model.transcribe.side_effect=[([segment('hello', [(0, 1.2, 'hello')])], None),
                                           ([segment('there friend', [(0, .5, 'there'), (.5, 1, ' friend')])], None)]
        self.stream.frames.extend(bytes(24 * RATE * 2)); self.stream.voiced=50
        self.stream.finish(final=False)
        self.stream.frames=bytearray(bytes(RATE * 2)); self.stream.voiced=20
        self.stream.finish(final=True)
        self.assertEqual(self.lines[-1][0], 'hello there friend')
    def test_translation_error_keeps_original_and_processing_continues(self):
        self.translation.translate.side_effect = [RuntimeError('private'), 'Привет']
        self.stream.publish('Hello.', 'en', None)
        self.stream.publish('Hello again.', 'en', None)
        self.assertEqual(self.lines[0][0], 'Hello.')
        self.assertIn('Не удалось перевести', self.lines[0][1])
        self.assertEqual(self.lines[1][1], 'Привет')
    def test_quiet_gain_preserves_silence_and_amplifies_weak_signal(self):
        from whisper_stream import amplify_quiet_audio
        self.assertTrue(np.array_equal(amplify_quiet_audio(np.zeros(RATE, dtype=np.float32)), np.zeros(RATE, dtype=np.float32)))
        quiet = np.full(RATE, .002, dtype=np.float32)
        self.assertGreater(float(np.mean(amplify_quiet_audio(quiet))), .002)
        loud = np.full(RATE, .1, dtype=np.float32)
        np.testing.assert_allclose(amplify_quiet_audio(loud), loud)

    def test_quiet_mode_does_not_trigger_on_low_hum_and_noise(self):
        self.stream.quiet_mode = True
        self.stream.gate.quiet_mode = True
        t = np.arange(4 * RATE) / RATE
        for samples in (np.zeros_like(t), .001 * np.sin(2 * np.pi * 50 * t),
                        np.random.default_rng(5).normal(0, .001, t.size)):
            pcm = (samples * 32767).astype('<i2').tobytes()
            for offset in range(0, len(pcm), 3200): self.stream.accept(pcm[offset:offset + 3200])
            self.stream.flush()
        self.model.detect_language.assert_not_called()
        self.assertEqual(self.lines, [])
    def test_german_without_translation_is_transcribed_at_normal_confidence(self):
        self.model.detect_language.return_value = ('de', .6, [])
        self.model.transcribe.return_value = ([segment('Guten Tag.', [(0, 1, 'Guten Tag.')])], None)
        self.stream.frames.extend(bytes(RATE * 2)); self.stream.voiced = 20
        self.stream.finish(final=True)
        self.assertEqual(self.lines[0][0], 'Guten Tag.')
        self.assertIn('установщик', self.lines[0][1])

    def test_nonfinal_empty_decode_keeps_audio(self):
        self.model.detect_language.return_value = ('en', .99, [])
        self.model.transcribe.return_value = ([], None)
        self.stream.frames.extend(bytes(24 * RATE * 2)); self.stream.voiced = 50
        self.stream.finish(final=False)
        self.assertEqual(len(self.stream.frames), 24 * RATE * 2)
        self.assertEqual(self.stream.next_window_bytes, 26 * RATE * 2)

    def test_long_unrecognized_audio_stops_with_explanation(self):
        from whisper_stream import UnrecognizedAudioError
        self.model.detect_language.return_value = ('en', .99, [])
        self.model.transcribe.return_value = ([], None)
        self.stream.frames.extend(bytes(30 * RATE * 2)); self.stream.voiced = 50
        self.stream.pending.extend(b'last')
        with self.assertRaisesRegex(UnrecognizedAudioError, 'Не удалось распознать') as error:
            self.stream.finish(final=False)
        self.assertEqual(len(self.stream.frames), 30 * RATE * 2)
        self.assertTrue(error.exception.pcm.endswith(b'last'))

    def test_tail_does_not_repeat_preview_words_missing_from_final(self):
        self.stream.preview = lambda value: None
        self.stream.stable_words.update('hello there'); self.stream.stable_words.update('hello there')
        self.model.detect_language.return_value = ('en', .99, [])
        self.model.transcribe.side_effect = [([segment('hello', [(0, .5, 'hello')])], None),
                                             ([segment('there friend', [(.2, .5, ' there'), (.5, .8, ' friend')])], None)]
        self.stream.frames.extend(bytes(2 * RATE * 2)); self.stream.voiced = 20
        with patch('whisper_stream.get_speech_timestamps', return_value=[{'start': 0, 'end': RATE}]):
            self.stream.finish(final=True)
        self.assertEqual(self.lines[0][0], 'hello there friend')

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
            deadline=time.monotonic()+5
            while not stream.stable_words.previous and time.monotonic()<deadline:
                threading.Event().wait(.02)
            self.assertTrue(stream.stable_words.previous)
            stream.clock+=RATE;stream.queue_preview()
            self.assertTrue(received.wait(5)); self.assertIn(('Hello there','','EN'), values)
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
        self.assertEqual([(x[0], x[2]) for x in self.lines], [('Hello', 'Голос 1'), ('there', 'Голос 2'), ('both', 'Голос не определён')])

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
