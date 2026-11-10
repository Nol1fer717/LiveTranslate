import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import diagnostics


class DiagnosticTests(unittest.TestCase):
    def test_vad_summary_contains_only_aggregate_values(self):
        with self.assertLogs('livetranslate', level='DEBUG') as captured:
            diagnostics.record_vad_summary(313, .42, 300)
        self.assertIn('кадров=313', captured.output[0])
        self.assertIn('максимум=0.420', captured.output[0])
        self.assertIn('причина=низкая_вероятность', captured.output[0])
    def test_crash_marker_is_reported_once_without_error_text(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA': tmp}):
            diagnostics.configure()
            try:
                try: raise RuntimeError('private audio transcript')
                except RuntimeError as error: diagnostics.log_error('worker', type(error), error.__traceback__)
                self.assertTrue(diagnostics.consume_crash_notice())
                self.assertFalse(diagnostics.consume_crash_notice())
            finally: diagnostics.shutdown()

    def test_session_error_creates_crash_marker(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA': tmp}):
            diagnostics.configure()
            try:
                try:
                    raise RuntimeError('session failed')
                except RuntimeError as error:
                    diagnostics.log_error('session', type(error), error.__traceback__)
                self.assertTrue(diagnostics.consume_crash_notice())
            finally:
                diagnostics.shutdown()

    def test_log_excludes_exception_message_and_records_stack(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA': tmp}):
            folder = diagnostics.configure()
            try:
                try:
                    raise ValueError('личный текст разговора')
                except ValueError as error:
                    diagnostics.log_error('test', type(error), error.__traceback__)
            finally:
                diagnostics.shutdown()
            text = (folder / 'application.log').read_text(encoding='utf-8')
            self.assertIn('ValueError', text)
            self.assertIn('test_diagnostics.py', text)
            self.assertNotIn('личный текст разговора', text)
