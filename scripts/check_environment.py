"""Короткая проверка установки без сложного экранирования PowerShell-команд."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import FFMPEG, FFPROBE  # noqa: E402
from backend.video import run  # noqa: E402

for binary in (FFMPEG, FFPROBE):
    print(run([binary, "-version"]).splitlines()[0])
