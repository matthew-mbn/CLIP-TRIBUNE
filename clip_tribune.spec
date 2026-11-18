# Сборка одним EXE; включаем только код и общие ресурсы, без базы и ключей.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import sys

root = Path(SPECPATH)
ffmpeg = next((root / ".tools" / "ffmpeg").glob("**/ffmpeg.exe"))
ffprobe = ffmpeg.with_name("ffprobe.exe")
datas = [
    (str(root / "assets"), "assets"),
    (str(root / "backend" / "migrations"), "backend/migrations"),
    (str(root / "docs" / "third-party-notices.txt"), "licenses"),
    (str(ffmpeg.parent.parent / "LICENSE"), "licenses/ffmpeg"),
    (str(ffmpeg.parent.parent / "README.txt"), "licenses/ffmpeg"),
] + collect_data_files("customtkinter") + collect_data_files("tzdata") + collect_data_files("yt_dlp_ejs")
a = Analysis([str(root / "launcher.py")], pathex=[str(root)],
    binaries=[(str(ffmpeg), "bin"), (str(ffprobe), "bin"),
              (str(Path(sys.executable).parent / "deno.exe"), "bin")], datas=datas,
    hiddenimports=collect_submodules("uvicorn") + ["sqlalchemy.dialects.sqlite", "sqlalchemy.dialects.postgresql.psycopg"],
    excludes=["pytest", "ruff", "PyInstaller"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="CLIP TRIBUNE", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    icon=str(root / "assets" / "app.ico"), version=str(root / "assets" / "version.txt"))
