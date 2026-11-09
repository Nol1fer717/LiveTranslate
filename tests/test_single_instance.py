import subprocess
import sys
import unittest
import uuid

from single_instance import SingleInstance


class SingleInstanceTests(unittest.TestCase):
    def test_second_process_is_blocked_until_first_releases_mutex(self):
        name = 'Local\\LiveTranslate.Test.' + uuid.uuid4().hex
        first = SingleInstance(name)
        self.addCleanup(first.close)
        self.assertTrue(first.is_primary)
        code = ('from single_instance import SingleInstance; import sys; '
                's=SingleInstance(sys.argv[1]); print(int(s.is_primary)); s.close()')
        def probe():
            return subprocess.check_output([sys.executable, '-c', code, name], text=True).strip()
        self.assertEqual(probe(), '0')
        first.close()
        self.assertEqual(probe(), '1')
