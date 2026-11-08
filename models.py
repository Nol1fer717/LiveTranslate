"""Restore model files for a fresh checkout using verified upstream archives."""
import hashlib
import shutil
from pathlib import Path
import tempfile
from urllib.request import urlretrieve
from zipfile import ZipFile
from huggingface_hub import hf_hub_download

DATA = Path(__file__).resolve().parent / "data"
WHISPER_REVISION = "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66"
WHISPER_FILES = {
    "model.bin": "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9",
    "config.json": "56a6d8110d311f19c8f0471e562832c7527f146b567275bfca59fcf7c184da9a",
    "tokenizer.json": "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
    "vocabulary.txt": "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
}
ARCHIVES = {
    "https://alphacephei.com/vosk/models/vosk-model-spk-0.4.zip":
        "a74d8f51144484813e16af689bb0f916b7a111e2347f467c4933c1166097b5a7",
    "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip":
        "961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4",
    "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip":
        "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498",
    "https://argos-net.com/v1/translate-en_ru-1_9.argosmodel":
        "591d743ae103752b88ffc38785c50421320f4eff93c8967e0d3d2e14d4e27811",
    "https://argos-net.com/v1/translate-ru_en-1_9.argosmodel":
        "e9ba8bf722d10a4a4c39f74289d5938fd47eac08dbe4ed0afd22d89445a5c3ac",
}


def install():
    DATA.mkdir(exist_ok=True)
    for url, expected in ARCHIVES.items():
        folder = Path(url).stem
        if (DATA / folder).is_dir():
            continue
        print(f"Загрузка {folder}…", flush=True)
        with tempfile.TemporaryDirectory(dir=DATA) as scratch:
            archive = Path(scratch) / "package.zip"
            urlretrieve(url, archive)
            with archive.open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != expected:
                    raise ValueError(f"Контрольная сумма {folder} не совпадает")
            with ZipFile(archive) as package:
                package.extractall(scratch)
            (Path(scratch) / folder).rename(DATA / folder)
    folder = DATA / "whisper-base"
    folder.mkdir(exist_ok=True)
    for name, expected in WHISPER_FILES.items():
        dest = folder / name
        if dest.is_file():
            with dest.open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() == expected:
                    continue
        with tempfile.TemporaryDirectory(dir=folder) as scratch:
            path = Path(scratch) / name
            shutil.copyfile(hf_hub_download("Systran/faster-whisper-base", name,
                                            revision=WHISPER_REVISION), path)
            with path.open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != expected:
                    raise ValueError(f"Контрольная сумма Whisper {name} не совпадает")
            path.replace(dest)


if __name__ == "__main__":
    install()
