import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from speaker_diarization import SpeakerDiarizer, RATE


class SpeakerDiarizationTests(unittest.TestCase):
    def test_distinct_speakers_in_same_window_cannot_share_identity(self):
        diarizer = SpeakerDiarizer.__new__(SpeakerDiarizer)
        rows = [SimpleNamespace(start=0, end=2, speaker=0), SimpleNamespace(start=2, end=4, speaker=1)]
        diarizer.diarizer = Mock()
        diarizer.diarizer.process.return_value.sort_by_start_time.return_value = rows
        diarizer.label = Mock(side_effect=['Голос 1', 'Голос 2'])
        result = diarizer.turns(np.ones(4 * RATE, dtype=np.float32))
        self.assertEqual([x[2] for x in result], ['Голос 1', 'Голос 2'])
        self.assertEqual(diarizer.label.call_args_list[1].args[1], {0})
