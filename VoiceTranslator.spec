# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files, collect_delvewheel_libs_directory

binaries = []
binaries += collect_dynamic_libs('vosk')
binaries += collect_dynamic_libs('ctranslate2')
for package in ('cublas', 'cudnn', 'cuda_nvrtc'):
    folder = Path(sys.prefix) / 'Lib' / 'site-packages' / 'nvidia' / package / 'bin'
    binaries += [(str(path), f'nvidia/{package}/bin') for path in folder.glob('*.dll')]
datas = collect_data_files('faster_whisper')
datas += [('installer/packages.json', '.')]
datas += collect_data_files('sacremoses')
datas, binaries = collect_delvewheel_libs_directory('av', datas=datas, binaries=binaries)


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=['_cffi_backend', 'huggingface_hub.file_download', 'huggingface_hub._snapshot_download'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VoiceTranslator',
    version='version_info.txt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VoiceTranslator',
)
