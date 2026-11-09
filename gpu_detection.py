"""Conservative NVIDIA detection shared by the app and installer downloader."""
import os
from pathlib import Path
import subprocess

MIN_TURBO_TOTAL_MIB = 8192
MIN_TURBO_FREE_MIB = 5120


def nvidia_memory():
    system_root = os.environ.get('SystemRoot', r'C:\Windows')
    candidates = [Path(system_root) / 'System32' / 'nvidia-smi.exe',
                  Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'NVIDIA Corporation' / 'NVSMI' / 'nvidia-smi.exe']
    for executable in candidates:
        if not executable.is_file():
            continue
        try:
            result = subprocess.run([str(executable), '--id=0', '--query-gpu=memory.total,memory.free', '--format=csv,noheader,nounits'],
                                    capture_output=True, text=True, timeout=5, check=True,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            total, free = (int(x.strip()) for x in result.stdout.strip().splitlines()[0].split(','))
            if total > 0 and 0 <= free <= total:
                return total, free
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            continue
    return None


def supports_turbo(memory, check_free=True):
    return bool(memory and memory[0] >= MIN_TURBO_TOTAL_MIB and
                (not check_free or memory[1] >= MIN_TURBO_FREE_MIB))
