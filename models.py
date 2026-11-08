"""Restore model files for a fresh checkout using verified upstream archives."""
import hashlib
from pathlib import Path
import tempfile
from urllib.request import urlretrieve
from zipfile import ZipFile

DATA = Path(__file__).resolve().parent / "data"
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


if __name__ == "__main__":
    install()
