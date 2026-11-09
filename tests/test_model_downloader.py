import hashlib
import io
import json
import queue
import tarfile
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from installer import model_downloader as downloader


def package(name, data, task=None):
    digest = hashlib.sha256(data).hexdigest()
    return {'name':name, 'url':'https://example.invalid/'+name, 'sha256':digest, 'task':task,
            'files':[{'path':'models/'+name, 'sha256':digest}]}

class DownloaderTests(unittest.TestCase):
    def test_background_install_extracts_verified_archive_and_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); output=root/'downloads'; output.mkdir(); target=root/'app'
            item=package('model.zip',b'x'); config=root/'packages.json'; config.write_text(json.dumps([item]),encoding='utf-8')
            with zipfile.ZipFile(output/'model.zip','w') as archive: archive.writestr('model/weights.bin',b'weights')
            with patch.object(downloader,'CONFIG',config):
                downloader.install_downloads(target,output,set(),threading.Event(),queue.SimpleQueue())
            self.assertEqual((target/'data/model/weights.bin').read_bytes(),b'weights')
            with zipfile.ZipFile(output/'model.zip','w') as archive: archive.writestr('../escape',b'bad')
            with patch.object(downloader,'CONFIG',config), self.assertRaises(ValueError):
                downloader.install_downloads(target,output,set(),threading.Event(),queue.SimpleQueue())
            self.assertFalse((target/'escape').exists())

    def test_huggingface_worker_downloads_and_verifies_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp); item=package('model.bin',b'valid')
            item.update(hf_repo='owner/model',hf_file='model.bin',hf_revision='revision')
            def start(command, **kwargs):
                folder=Path(command[-1]); folder.mkdir(parents=True)
                (folder/'model.bin').write_bytes(b'valid')
                process=unittest.mock.Mock(); process.poll.return_value=0; process.returncode=0
                return process
            with patch.object(downloader.subprocess,'Popen',side_effect=start):
                downloader.download(item,output,threading.Event(),lambda n:None)
            self.assertEqual((output/'model.bin').read_bytes(),b'valid')

    def test_extracts_only_verified_model_from_speaker_archive(self):
        model = b'model data'
        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode='w:bz2') as archive:
            entry = tarfile.TarInfo('model/model.onnx'); entry.size = len(model)
            archive.addfile(entry, io.BytesIO(model))
        blob = archive_bytes.getvalue()
        item = package('speaker.onnx', model, 'speakers')
        item['sha256'] = hashlib.sha256(blob).hexdigest()
        item['archive_member'] = 'model/model.onnx'
        with tempfile.TemporaryDirectory() as tmp, patch.object(downloader, 'urlopen', return_value=io.BytesIO(blob)):
            downloader.download(item, Path(tmp), threading.Event(), lambda n: None)
            self.assertEqual((Path(tmp)/'speaker.onnx').read_bytes(), model)

    def test_optional_gpu_failure_keeps_base_install_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); config = root/'packages.json'
            config.write_text(json.dumps([package('base',b'base'), package('gpu',b'gpu','nvidia'), package('turbo',b'turbo','turbo')]),encoding='utf-8')
            def fake_download(item, output, cancelled, notify):
                if item['name'] == 'gpu': raise RuntimeError('offline')
                (output/item['name']).write_bytes(item['name'].encode())
            with patch.object(downloader,'CONFIG',config), patch.object(downloader,'download',side_effect=fake_download):
                downloader.prepare(root/'none', root/'out', {'nvidia','turbo'}, threading.Event(), queue.SimpleQueue())
            self.assertTrue((root/'out'/'base').is_file())
            self.assertFalse((root/'out'/'turbo').exists())
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
