"""Скачивание одного публичного видео YouTube / Twitch через yt-dlp.

Отдельный процесс нужен для честной отмены: даже сетевой запрос или слияние
дорожек FFmpeg можно остановить, не закрывая окно и не блокируя очередь.
"""

import json
import multiprocessing
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psutil

from .config import FFMPEG, MAX_UPLOAD, ROOT
from .video import Cancelled
from .source_identity import source_identity


def validate_url(value):
    """Принимаем конкретный ролик, а не канал, плейлист или произвольный сайт."""
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Нужна HTTPS-ссылка на видео YouTube или Twitch")
    host = (parsed.hostname or "").lower()
    video_id = None
    if host == "youtu.be":
        video_id = parsed.path.strip("/")
    elif host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif re.fullmatch(r"/(shorts|live|embed)/[\w-]{11}/?", parsed.path):
            video_id = parsed.path.rstrip("/").split("/")[-1]
    if video_id is not None and re.fullmatch(r"[\w-]{11}", video_id, flags=re.ASCII):
        return f"https://www.youtube.com/watch?v={video_id}"
    if host in ("twitch.tv", "www.twitch.tv", "m.twitch.tv"):
        if re.fullmatch(r"/videos/\d+/?", parsed.path):
            return "https://www.twitch.tv" + parsed.path.rstrip("/")
        if re.fullmatch(r"/[\w-]+/clip/[\w-]+/?", parsed.path, flags=re.ASCII):
            return "https://www.twitch.tv" + parsed.path.rstrip("/")
    if host == "clips.twitch.tv" and re.fullmatch(r"/[\w-]+/?", parsed.path, flags=re.ASCII):
        return "https://clips.twitch.tv" + parsed.path.rstrip("/")
    raise ValueError(
        "Поддерживаются отдельные видео/Shorts YouTube и записи/клипы Twitch. Ссылка на канал не подходит"
    )


def deno_path():
    for path in (ROOT / "bin" / "deno.exe", Path(sys.executable).parent / "deno.exe"):
        if path.is_file():
            return str(path)
    return shutil.which("deno")


def reject_media(info, *, incomplete=False):
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
        return "Дождитесь завершения трансляции и обработки записи"
    if (info.get("duration") or 0) > 8 * 3600:
        return "Поддерживаются записи длительностью до 8 часов"
    if info.get("availability") in ("private", "premium_only", "subscriber_only", "needs_auth"):
        return "Видео закрыто или требует входа. Импортируйте доступный вам локальный файл"
    return None


def write_status(folder, name, data):
    target = folder / name
    temporary = target.with_suffix(".writing")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)


def _download(url, height, folder):
    """В дочернем процессе нет SQL и Tkinter — только загрузчик и временные файлы."""
    import yt_dlp

    folder = Path(folder)
    last_progress = 0.0

    def progress(data):
        nonlocal last_progress
        if time.monotonic() - last_progress < 0.5 and data.get("status") != "finished":
            return
        last_progress = time.monotonic()
        received = data.get("downloaded_bytes", 0)
        total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
        if received > MAX_UPLOAD or shutil.disk_usage(folder).free < 1024**3:
            raise ValueError("Превышен размер 20 ГБ или осталось меньше 1 ГБ на диске")
        write_status(
            folder,
            "progress.json",
            dict(
                progress=min(90, received / total * 90) if total else 5,
                message=f"Загрузка: {received / 1024**2:.1f} МБ"
                if data.get("status") != "finished"
                else "Слияние видео и звука",
            ),
        )

    class QuietLog:
        def debug(self, message):
            pass

        def warning(self, message):
            pass

        def error(self, message):
            pass

    options = dict(
        outtmpl=str(folder / "source.%(ext)s"),
        format=f"bv*[height<={height}]+ba/b[height<={height}]",
        format_sort=["vcodec:h264", "acodec:aac"],
        merge_output_format="mp4",
        ffmpeg_location=str(Path(FFMPEG).parent),
        noplaylist=True,
        cachedir=False,
        quiet=True,
        noprogress=True,
        logger=QuietLog(),
        progress_hooks=[progress],
        match_filter=reject_media,
        socket_timeout=15,
        retries=2,
        fragment_retries=2,
        concurrent_fragment_downloads=1,
        max_filesize=MAX_UPLOAD,
        windowsfilenames=True,
        restrictfilenames=True,
    )
    runtime = deno_path()
    if runtime:
        options["js_runtimes"] = {"deno": {"path": runtime}}
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=False)
            if not info or info.get("_type") in ("playlist", "multi_video"):
                raise ValueError("Нужна ссылка на один доступный ролик")
            if reason := reject_media(info):
                raise ValueError(reason)
            downloader.process_info(info)
        files = [path for path in folder.glob("source.*") if path.suffix in (".mp4", ".mkv", ".webm")]
        if len(files) != 1 or not files[0].stat().st_size:
            raise ValueError("Загрузчик не создал готовый видеофайл")
        write_status(
            folder,
            "result.json",
            dict(
                path=str(files[0]),
                title=str(info.get("title") or "Видео")[:180],
                source_identity=source_identity(info, url),
            ),
        )
    except Exception as error:
        message = str(error)[:1200]
        if "Requested format is not available" in message:
            message = "Для этого видео нет формата в выбранном качестве. Попробуйте 1080p или импорт локального файла"
        write_status(folder, "result.json", {"error": message})


def terminate_tree(process):
    try:
        root = psutil.Process(process.pid)
        children = root.children(recursive=True)
        for child in [*children, root]:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs([root, *children], timeout=3)
        for child in alive:
            child.kill()
    except psutil.NoSuchProcess:
        pass


def download(url, height, folder, cancelled, on_progress):
    url = validate_url(url)
    if cancelled():
        raise Cancelled()
    process = multiprocessing.Process(target=_download, args=(url, height, str(folder)))
    process.start()
    started = time.monotonic()
    last_status = None
    try:
        while process.is_alive():
            if cancelled():
                raise Cancelled()
            if time.monotonic() - started > 4 * 3600:
                raise ValueError("Загрузка превысила 4 часа; повторите позднее")
            try:
                status = (Path(folder) / "progress.json").read_text(encoding="utf-8")
                if status != last_status:
                    on_progress(json.loads(status))
                    last_status = status
            except OSError, ValueError:
                pass
            time.sleep(0.2)
        process.join()
        if cancelled():
            raise Cancelled()
        result_path = Path(folder) / "result.json"
        if not result_path.exists():
            raise ValueError("Загрузчик завершился без результата")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("error"):
            raise ValueError("Не удалось скачать видео. Сервис мог ограничить доступ.\n" + result["error"])
        return Path(result["path"]), result["title"], result["source_identity"]
    finally:
        if process.is_alive():
            terminate_tree(process)
        process.join(timeout=3)
