"""Локальная Whisper base: одна загрузка модели, дальше звук остаётся на компьютере."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import urllib.request
from .config import ROOT, STORAGE, FFMPEG
from . import video

MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
MODEL_HASH = "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe"
MODEL_SIZE = 147951465


def model_path():
    return STORAGE / "speech" / "ggml-base.bin"


def engine_path():
    bundled = ROOT / "bin" / "whisper" / "whisper-cli.exe"
    return bundled if bundled.exists() else ROOT / ".tools" / "whisper" / "whisper-cli.exe"


def ready():
    path = model_path()
    return engine_path().is_file() and path.is_file() and path.stat().st_size == MODEL_SIZE


def install(cancelled=lambda: False):
    target = model_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".download")
    try:
        digest = hashlib.sha256()
        with urllib.request.urlopen(MODEL_URL, timeout=30) as response, temporary.open("wb") as output:
            size = 0
            while chunk := response.read(1024 * 1024):
                if cancelled():
                    raise video.Cancelled()
                size += len(chunk)
                if size > MODEL_SIZE:
                    raise ValueError("Сервер вернул неверный размер модели")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != MODEL_HASH:
            raise ValueError("Контрольная сумма модели не совпала. Повторите загрузку")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def transcribe(path, cancelled=lambda: False):
    from .youtube import secret
    from .providers import HttpSpeechProvider

    if not ready():
        if secret("SPEECH_API_URL"):
            return HttpSpeechProvider().transcribe(str(path))
        raise ValueError("В библиотеке откройте «Субтитры» и скачайте модель распознавания (148 МБ)")
    if not video.probe(path)["audio"]:
        raise ValueError("В этом ролике нет звуковой дорожки")
    with TemporaryDirectory(dir=STORAGE / "temp") as folder:
        wav = Path(folder) / "speech.wav"
        result = Path(folder) / "speech"
        video.run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-i",
                str(path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(wav),
            ],
            cancelled,
        )
        video.run(
            [
                str(engine_path()),
                "-m",
                str(model_path()),
                "-f",
                str(wav),
                "-l",
                "auto",
                "-t",
                "4",
                "-oj",
                "-of",
                str(result),
                "-ml",
                "40",
                "-sow",
            ],
            cancelled,
        )
        data = json.loads(result.with_suffix(".json").read_text(encoding="utf-8"))
        return [
            dict(start=r["offsets"]["from"] / 1000, end=r["offsets"]["to"] / 1000, text=r["text"].strip())
            for r in data["transcription"]
            if r["text"].strip() and r["offsets"]["to"] > r["offsets"]["from"]
        ]
