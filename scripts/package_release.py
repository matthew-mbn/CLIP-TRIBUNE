"""Архив для пользователей: EXE, инструкция, фирменные ресурсы и лицензии.

Запуск: python scripts/package_release.py dist/0.8.0
Видеоматериалы, база, .env и окружение разработчика сюда не попадают.
"""

import hashlib
import importlib.metadata
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    folder = (ROOT / (sys.argv[1] if len(sys.argv) > 1 else "dist")).resolve()
    executable = folder / "CLIP TRIBUNE.exe"
    if not executable.is_file():
        raise SystemExit("Сначала соберите CLIP TRIBUNE.exe")
    archive = folder / "CLIP-TRIBUNE-Windows-x64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        output.write(executable, executable.name)
        for relative in (
            "README.md",
            "assets/banner.svg",
            "assets/logo.svg",
            "docs/third-party-notices.txt",
            "docs/tiktok.md",
            "docs/live-streams.md",
            "docs/release-0.8.0.md",
            "docs/editing.md",
            "docs/autopublishing.md",
            "docs/webcam.md",
            "docs/terms-ru.html",
            "docs/privacy-ru.html",
            "docs/terms.html",
            "docs/privacy.html",
            "docs/index.html",
            "docs/site.css",
            "docs/site-assets/logo.svg",
            "docs/providers.md",
            "docs/learning-python.md",
            "docs/verification.md",
        ):
            output.write(ROOT / relative, relative)
        # Тексты лицензий берём из именно тех пакетов, которые установлены для сборки.
        names = (
            "yt-dlp",
            "yt-dlp-ejs",
            "deno",
            "customtkinter",
            "pillow",
            "mutagen",
            "requests",
            "urllib3",
            "pycryptodomex",
            "brotli",
            "websockets",
            "fastapi",
            "uvicorn",
            "sqlalchemy",
            "alembic",
            "cryptography",
            "psutil",
            "httpx",
            "certifi",
            "python-dotenv",
            "pydantic",
        )
        for name in names:
            distribution = importlib.metadata.distribution(name)
            for file in distribution.files or []:
                if any(word in file.name.lower() for word in ("license", "copying", "notice")):
                    path = distribution.locate_file(file)
                    if path.is_file() and path.suffix not in (".py", ".pyc"):
                        output.write(path, "licenses/" + name + "/" + str(file).replace("\\", "/"))
        ffmpeg = next((ROOT / ".tools" / "ffmpeg").glob("**/ffmpeg.exe"))
        for name in ("LICENSE", "README.txt"):
            output.write(ffmpeg.parent.parent / name, "licenses/ffmpeg/" + name)
        output.write(ROOT / ".tools/whisper/LICENSE", "licenses/whisper/LICENSE")
        output.write(ROOT / ".tools/whisper/MODEL_LICENSE", "licenses/whisper/MODEL_LICENSE")
        python_license = Path(sys.base_prefix) / "LICENSE.txt"
        if python_license.is_file():
            output.write(python_license, "licenses/python/LICENSE.txt")
    checksums = []
    for path in (executable, archive):
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        checksums.append(f"{digest}  {path.name}")
        print(f"{path.name}: {path.stat().st_size / 1024**2:.1f} MiB")
    (folder / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
