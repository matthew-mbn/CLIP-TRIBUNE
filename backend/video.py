"""AutoClip Engine: объяснимый анализ изображения и звука без платных моделей.

FFmpeg работает отдельным процессом. Python управляет им и проверяет отмену.
Оценка отражает измеренную динамику, а не вероятность вирусного успеха.
"""

import array
import json
import math
import os
import statistics
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import psutil

from .config import FFMPEG, FFPROBE, STORAGE


class Cancelled(Exception):
    """Отмена пользователем — отдельное событие, а не ошибка FFmpeg."""


def run(command, cancelled=lambda: False, timeout=7200, memory_mb=4096):
    """Запускаем список аргументов без shell, поэтому ввод не становится командой."""
    with TemporaryDirectory(dir=STORAGE / "temp") as temp:
        output = Path(temp) / "output.log"
        with output.open("wb") as log_file:
            process = subprocess.Popen(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            started = time.monotonic()
            try:
                while process.poll() is None:
                    if cancelled():
                        raise Cancelled("Обработка отменена")
                    if time.monotonic() - started > timeout:
                        raise RuntimeError("Превышено время обработки")
                    try:
                        if psutil.Process(process.pid).memory_info().rss > memory_mb * 1024**2:
                            raise RuntimeError("FFmpeg превысил лимит оперативной памяти")
                    except psutil.NoSuchProcess:
                        pass
                    time.sleep(0.2)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
        text = output.read_text(encoding="utf-8", errors="replace")
        if process.returncode:
            raise RuntimeError("Ошибка FFmpeg/FFprobe: " + text[-1600:])
        return text


def probe(path):
    if not Path(path).is_file():
        raise ValueError("Видеофайл не найден")
    data = json.loads(
        run(
            [
                FFPROBE,
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            timeout=30,
        )
    )
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if not video:
        raise ValueError("В файле нет видеодорожки")
    duration = float(data["format"].get("duration", video.get("duration", 0)))
    if not 0 < duration <= 8 * 3600:
        raise ValueError("Поддерживается видео длительностью до 8 часов")
    numerator, denominator = video.get("avg_frame_rate", "30/1").split("/")
    return dict(
        duration=duration,
        width=video["width"],
        height=video["height"],
        fps=float(numerator) / max(float(denominator), 1),
        audio=any(s["codec_type"] == "audio" for s in data["streams"]),
        codec=video["codec_name"],
    )


def analyze(path, metadata, cancelled=lambda: False):
    """Один маленький серый кадр и RMS звука на секунду экономят память.

    Межкадровая разница даёт динамику; крупный скачок — вероятную смену сцены.
    Это не распознавание погонь или шуток. Причины отбора сохраняются отдельно.
    """
    with TemporaryDirectory(dir=STORAGE / "temp") as temp:
        frames = Path(temp) / "frames.raw"
        run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(path),
                "-an",
                "-vf",
                "fps=1,scale=64:36,format=gray",
                "-f",
                "rawvideo",
                str(frames),
            ],
            cancelled,
        )
        motion, hashes = [], []
        previous = None
        with frames.open("rb") as stream:
            while frame := stream.read(64 * 36):
                if cancelled():
                    raise Cancelled()
                delta = sum(abs(a - b) for a, b in zip(frame, previous)) / len(frame) if previous else 0
                motion.append(delta / 255)
                # Средние яркости 8x8 блоков образуют простой perceptual hash.
                blocks = [
                    sum(frame[y * 64 + x : y * 64 + x + 8]) / 8
                    for y in range(0, 36, 5)
                    for x in range(0, 64, 8)
                ]
                mean = statistics.mean(blocks)
                hashes.append("".join("1" if value > mean else "0" for value in blocks))
                previous = frame
        audio = [0.0] * len(motion)
        if metadata["audio"]:
            pcm = Path(temp) / "audio.pcm"
            run(
                [
                    FFMPEG,
                    "-v",
                    "error",
                    "-y",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-i",
                    str(path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "8000",
                    "-f",
                    "s16le",
                    str(pcm),
                ],
                cancelled,
            )
            with pcm.open("rb") as stream:
                for index in range(len(audio)):
                    samples = array.array("h", stream.read(16000))
                    if samples:
                        audio[index] = math.sqrt(sum(x * x for x in samples) / len(samples)) / 32768
        return dict(
            motion=motion,
            audio=audio,
            hashes=hashes,
            scenes=[i for i, value in enumerate(motion) if value > 0.18],
        )


def similarity(first, second):
    return 1 - sum(a != b for a, b in zip(first, second)) / max(len(first), len(second), 1)


def select_candidates(
    features, duration, length, count, used=(), min_score=0, preset="Gaming Viral", start_min=0
):
    """Ранжируем окна, затем исключаем пересечения и почти одинаковые сцены."""
    if duration < length:
        raise ValueError(f"Исходник короче выбранной нарезки ({length} сек.)")
    starts = set(range(0, max(1, int(duration - length) + 1), max(5, length // 3)))
    starts.update(s for s in features["scenes"] if s + length <= duration)
    candidates = []
    for start in sorted(starts):
        if start < start_min:
            continue
        motion = features["motion"][start : start + length]
        audio = features["audio"][start : start + length]
        movement = min(1, statistics.mean(motion or [0]) / 0.15)
        sound = min(1, max(audio or [0]) / 0.25)
        cuts = sum(start <= s < start + length for s in features["scenes"])
        # Cinematic предпочитает спокойное движение; прочие стили — динамику.
        movement_weight = 1 - movement if preset == "Cinematic" else movement
        score = round(100 * (0.6 * movement_weight + 0.25 * sound + 0.15 * min(cuts / 3, 1)), 1)
        middle = min(len(features["hashes"]) - 1, start + length // 2)
        fingerprint = features["hashes"][middle] if middle >= 0 else ""
        candidates.append(
            dict(
                start=float(start),
                duration=float(length),
                score=score,
                fingerprint=fingerprint,
                reasons=[
                    f"Динамика кадра: {movement:.0%}",
                    f"Пик звука: {sound:.0%}",
                    f"Вероятных смен сцен: {cuts}",
                    "Эвристический отбор; смысл и завершённость сюжета требуют просмотра",
                ],
            )
        )
    chosen = []
    for candidate in sorted(candidates, key=lambda c: (-c["score"], c["start"])):
        if candidate["score"] < min_score:
            continue
        duplicate = False
        for other in [*used, *chosen]:
            overlap = min(candidate["start"] + length, other["start"] + other["duration"]) - max(
                candidate["start"], other["start"]
            )
            if overlap > 0 or (
                other.get("fingerprint") and similarity(candidate["fingerprint"], other["fingerprint"]) > 0.98
            ):
                duplicate = True
                break
        if not duplicate:
            chosen.append(candidate)
        if len(chosen) >= count:
            break
    return chosen


def render(path, output, candidate, options, metadata, cancelled=lambda: False, subtitle_path=None):
    if subtitle_path:
        from .captions import burn

        clean = Path(output).with_suffix(".clean.mp4")
        render(path, clean, candidate, options, metadata, cancelled)
        try:
            return burn(clean, output, subtitle_path, options, cancelled)
        except Exception:
            clean.unlink(missing_ok=True)
            Path(output).unlink(missing_ok=True)
            raise
    width = int(options.get("resolution", "720"))
    height = width * 16 // 9
    from .composition import build, media_input, ad_timing

    _, ad_length, paused = ad_timing(options, candidate["duration"])
    output_duration = candidate["duration"] + (ad_length if paused else 0)

    extra_inputs, graph, current, has_audio, width, height = build(
        options, metadata, width, height, candidate["duration"]
    )
    filters = f"[{current}]null"
    if options.get("preset") == "Cinematic":
        filters += ",eq=contrast=1.05:saturation=0.9"
    if options.get("preset") == "Action":
        filters += ",eq=contrast=1.08:saturation=1.08"
    title_file = None
    if options.get("title_overlay") and options.get("theme"):
        title_file = Path(output).with_suffix(".title.txt")
        title_file.write_text(options["theme"][:80], encoding="utf-8")
        escaped = str(title_file).replace("\\", "/").replace(":", "\\:")
        filters += f",drawtext=textfile='{escaped}':expansion=none:fontcolor=white:fontsize=32:box=1:boxcolor=black@0.6:x=(w-tw)/2:y=h*0.12"
    graph.append(filters + "[out]")
    command = [FFMPEG, "-v", "error", "-y"]
    command += media_input(path, start=candidate["start"]) + extra_inputs
    command += [
        "-t",
        str(output_duration),
        "-filter_complex_threads",
        "1",
        "-filter_complex",
        ";".join(graph),
        "-map",
        "[out]",
    ]
    if has_audio:
        command += ["-map", "[audio]"]
    command += [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        "-threads",
        str(options.get("threads", 2)),
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(output),
    ]
    try:
        run(command, cancelled, memory_mb=options.get("memory_limit_mb", 4096))
        result = probe(output)
        if abs(result["duration"] - output_duration) > 1:
            raise RuntimeError("Длительность экспорта не совпала с ожидаемой")
        if (result["width"], result["height"]) != (width, height):
            raise RuntimeError("Неверное разрешение экспорта")
        return result
    except Exception:
        Path(output).unlink(missing_ok=True)
        raise
    finally:
        if title_file:
            title_file.unlink(missing_ok=True)


def thumbnail(video, target):
    run(
        [FFMPEG, "-v", "error", "-y", "-i", str(video), "-frames:v", "1", "-vf", "scale=240:-2", str(target)],
        timeout=30,
    )


def make_test_video(target, duration=48):
    """Синтетический материал без чужих авторских прав, не фиктивный результат."""
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(target),
        ]
    )
