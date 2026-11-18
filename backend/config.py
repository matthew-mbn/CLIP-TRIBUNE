import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# В exe ресурсы распаковываются во временную папку, данные живут постоянно в AppData.
FROZEN = getattr(sys, "frozen", False)
DATA_ROOT = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "CLIP TRIBUNE" if FROZEN else ROOT
load_dotenv(DATA_ROOT / ".env")
STORAGE = Path(os.getenv("STORAGE_ROOT", str(DATA_ROOT / "storage"))).resolve()
STORAGE.mkdir(parents=True, exist_ok=True)
for name in ("sources", "clips", "temp", "logs"):
    (STORAGE / name).mkdir(exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{STORAGE / 'clip_tribune.db'}")
REDIS_URL = os.getenv("REDIS_URL", "")


def binary(name):
    configured = os.getenv(name.upper() + "_PATH")
    if configured:
        return configured
    bundled = ROOT / "bin" / (name + ".exe")
    if bundled.exists():
        return str(bundled)
    found = shutil.which(name)
    if found:
        return found
    return next((str(p) for p in (ROOT / ".tools" / "ffmpeg").glob(f"**/{name}.exe")), name)


FFMPEG = binary("ffmpeg")
FFPROBE = binary("ffprobe")
MAX_UPLOAD = 20 * 1024**3
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
PORT = int(os.getenv("CLIP_TRIBUNE_PORT", "8765"))
BASE_URL = f"http://127.0.0.1:{PORT}"
