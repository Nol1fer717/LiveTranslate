import hashlib
import io
import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from installer import model_downloader as downloader


def package(name, data, task=None):
    digest = hashlib.sha256(data).hexdigest()
    return {'name':name, 'url':'https://example.invalid/'+name, 'sha256':digest, 'task':task,
            'files':[{'path':'models/'+name, 'sha256':digest}]}

class DownloaderTests(unittest.TestCase):
    def test_existing_files_are_verified_and_only_missing_packages_are_downloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root/'target'; output = root/'output'; (target/'models').mkdir(parents=True)
            (target/'models'/'good.bin').write_bytes(b'valid')
            (target/'models'/'bad.bin').write_bytes(b'corrupt')
            packages = [package('good.bin', b'valid'), package('bad.bin', b'correct'), package('optional.bin', b'optional', 'german')]
            config = root/'packages.json'; config.write_text(json.dumps(packages),encoding='utf-8')
            opened=[]
            def fake_open(req, timeout): opened.append(req.full_url); return io.BytesIO(b'correct')
            with patch.object(downloader,'CONFIG',config), patch.object(downloader,'urlopen',side_effect=fake_open):
                downloader.prepare(target, output, set(), threading.Event(), queue.SimpleQueue())
            self.assertEqual(opened, ['https://example.invalid/bad.bin'])
            self.assertEqual((output/'bad.bin').read_bytes(), b'correct')
            self.assertFalse((output/'good.bin').exists()); self.assertFalse((output/'optional.bin').exists())

    def test_downloads_run_in_parallel_and_verify_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); config=root/'packages.json'; config.write_text(json.dumps([package('a',b'a'), package('b',b'b')]),encoding='utf-8')
            barrier=threading.Barrier(2, timeout=3)
            def fake_open(req, timeout):
                barrier.wait(); return io.BytesIO(req.full_url.rsplit('/',1)[-1].encode())
            with patch.object(downloader,'CONFIG',config), patch.object(downloader,'urlopen',side_effect=fake_open):
                downloader.prepare(root/'none', root/'out', set(), threading.Event(), queue.SimpleQueue())
            self.assertEqual((root/'out'/'a').read_bytes(),b'a'); self.assertEqual((root/'out'/'b').read_bytes(),b'b')

    def test_hash_failure_does_not_install_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=package('model', b'correct')
            with patch.object(downloader,'urlopen',return_value=io.BytesIO(b'bad')), patch.object(downloader.time,'sleep'):
                with self.assertRaises(RuntimeError): downloader.download(p,root,threading.Event(),lambda n:None)
            self.assertFalse((root/'model').exists()); self.assertFalse((root/'model.part').exists())

if __name__=='__main__': unittest.main()
