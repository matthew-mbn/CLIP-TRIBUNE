"""Запись прямого эфира без блокировки монтажа и интерфейса.

yt-dlp получает актуальные адреса дорожек. FFmpeg сохраняет небольшие MKV без
перекодирования. В очередь монтажа попадают только закрытые части; открытый файл
никогда не читается монтажным воркером. Подписанные адреса живут только в памяти.
"""

import csv
import multiprocessing
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import getproxies

from sqlalchemy import select, update

from .config import FFMPEG, STORAGE
from .database import Session, settings
from .downloads import deno_path, terminate_tree, validate_url
from .models import LiveRecording, LiveSegment, RenderJob, now
from .security import inside
from .source_identity import source_identity
from . import video

ACTIVE = ("pending", "connecting", "recording", "reconnecting", "stopping")
PART_PATTERN = re.compile(r"capture_\d{2}_\d{6}\.mkv$")


def validate_live_url(value):
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Нужна HTTPS-ссылка на эфир YouTube или канал Twitch")
    host = (parsed.hostname or "").lower()
    if host in ("twitch.tv", "www.twitch.tv", "m.twitch.tv"):
        name = parsed.path.strip("/")
        if re.fullmatch(r"[a-zA-Z0-9_]{3,25}", name) and name.lower() not in {
            "videos",
            "directory",
            "downloads",
            "settings",
            "subscriptions",
            "inventory",
        }:
            return "https://www.twitch.tv/" + name.lower(), "twitch"
        raise ValueError("Для эфира Twitch нужна ссылка на канал, например twitch.tv/имя")
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        if re.fullmatch(r"/@[\w.-]+/live/?", parsed.path):
            return "https://www.youtube.com" + parsed.path.rstrip("/"), "youtube"
        if re.fullmatch(r"/channel/[\w-]+/live/?", parsed.path, flags=re.ASCII):
            return "https://www.youtube.com" + parsed.path.rstrip("/"), "youtube"
    canonical = validate_url(value)
    if urlparse(canonical).hostname != "www.youtube.com":
        raise ValueError("Здесь нужны прямой эфир YouTube или канал Twitch")
    return canonical, "youtube"


class QuietLog:
    # Не сохраняем диагностические сообщения загрузчика: в них встречаются signed URL.
    def debug(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass


def resolve_stream(url, height):
    """YouTube часто отдаёт видео и звук раздельно, Twitch — вместе."""
    import yt_dlp

    options = dict(
        quiet=True,
        no_warnings=True,
        logger=QuietLog(),
        cachedir=False,
        noplaylist=True,
        socket_timeout=15,
        retries=1,
        extractor_retries=1,
        format=(
            f"bv*[protocol^=m3u8][height<={height}]+ba[protocol^=m3u8]/"
            f"b[protocol^=m3u8][height<={height}]/bv*[height<={height}]+ba/b[height<={height}]"
        ),
        format_sort=["vcodec:h264", "acodec:aac"],
    )
    if runtime := deno_path():
        options["js_runtimes"] = {"deno": {"path": runtime}}
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=False)
    except Exception as error:
        raise ValueError(
            "Эфир недоступен. Проверьте ссылку, соединение и доступность трансляции без входа"
        ) from error
    if not info or info.get("_type") in ("playlist", "multi_video"):
        raise ValueError("Нужна одна текущая трансляция")
    if not info.get("is_live") and info.get("live_status") != "is_live":
        raise ValueError("По ссылке сейчас нет прямого эфира. Для готовой записи используйте «Источники»")
    if info.get("availability") in ("private", "premium_only", "subscriber_only", "needs_auth"):
        raise ValueError("Эфир требует закрытого доступа; эта версия записывает общедоступные трансляции")
    formats = info.get("requested_formats") or [info]
    streams = []
    for item in formats:
        stream_url = item.get("url", "")
        if urlparse(stream_url).scheme not in ("http", "https"):
            raise ValueError("Сервис вернул неподдерживаемый протокол трансляции")
        streams.append(
            dict(
                url=stream_url,
                headers=item.get("http_headers") or info.get("http_headers") or {},
                video=item.get("vcodec") != "none",
                audio=item.get("acodec") != "none",
            )
        )
    if not any(item["video"] for item in streams):
        raise ValueError("В трансляции не найдена видеодорожка")
    return str(info.get("title") or "Прямой эфир")[:220], streams, source_identity(info, url)


def stream_inputs(streams):
    """Сетевые параметры общие для записи и одного кадра предпросмотра."""
    command = []
    proxies = getproxies()
    proxy = proxies.get("https") or proxies.get("http")
    for stream in streams:
        command += [
            "-rw_timeout",
            "15000000",
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "3",
            "-protocol_whitelist",
            "http,https,httpproxy,tcp,tls,crypto",
        ]
        # FFmpeg не читает системный прокси Windows, в отличие от Python/yt-dlp.
        if proxy and urlparse(proxy).scheme == "http":
            command += ["-http_proxy", proxy]
        for header, option in (("User-Agent", "-user_agent"), ("Referer", "-referer")):
            value = stream["headers"].get(header, "")
            if value and not any(c in value for c in "\r\n"):
                command += [option, value[:2048]]
        command += ["-i", stream["url"]]
    return command


def capture_command(streams, folder, attempt, seconds):
    """Список аргументов, а не shell-команда. Имена выходных файлов задаём сами."""
    command = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"] + stream_inputs(streams)
    video_index = next(i for i, item in enumerate(streams) if item["video"])
    audio_index = next((i for i, item in enumerate(streams) if item["audio"]), None)
    command += ["-map", f"{video_index}:v:0"]
    if audio_index is not None:
        command += ["-map", f"{audio_index}:a:0?"]
    command += [
        "-c",
        "copy",
        "-f",
        "segment",
        "-segment_time",
        str(seconds),
        "-reset_timestamps",
        "1",
        "-segment_list_type",
        "csv",
        "-segment_list",
        str(folder / f"parts_{attempt:02}.csv"),
        str(folder / f"capture_{attempt:02}_%06d.mkv"),
    ]
    return command


def set_state(identity, **values):
    with Session() as session:
        item = session.get(LiveRecording, identity)
        if not item:
            return
        # Запоздалый прогресс не должен отменить нажатую пользователем остановку.
        if item.status == "stopping" and values.get("status") in ("connecting", "recording", "reconnecting"):
            values.pop("status", None)
            values.pop("message", None)
        for key, value in values.items():
            setattr(item, key, value)
        item.updated_at = now()
        session.commit()


def stopped(identity, event):
    if event.is_set():
        return True
    with Session() as session:
        item = session.get(LiveRecording, identity)
        return not item or item.status == "stopping" or item.active_slot is None


def register_parts(identity, paths):
    """Повторное сканирование безопасно: один файл получает одну запись в базе."""
    folder = inside(STORAGE / "live" / identity)
    with Session() as session:
        existing = session.scalars(select(LiveSegment).where(LiveSegment.recording_id == identity)).all()
        names = {part.name for part in existing}
        offset = sum(part.duration for part in existing)
        for path in sorted(paths):
            path = Path(path).resolve()
            if path.parent != folder or not PART_PATTERN.fullmatch(path.name) or path.name in names:
                continue
            if not path.is_file() or path.stat().st_size < 1024:
                continue
            try:
                metadata = video.probe(path)
            except ValueError, RuntimeError:
                continue  # Незавершённый файл после аварии остаётся для ручного восстановления.
            duration = metadata["duration"]
            if duration <= 0:
                continue
            session.add(
                LiveSegment(
                    recording_id=identity,
                    name=path.name,
                    path=str(path),
                    start=offset,
                    duration=duration,
                    size=path.stat().st_size,
                )
            )
            offset += duration
            names.add(path.name)
        item = session.get(LiveRecording, identity)
        if item:
            item.seconds = offset
            item.bytes = sum(p.stat().st_size for p in folder.glob("capture_*.mkv"))
            item.updated_at = now()
        session.commit()


def closed_paths(folder, attempt):
    try:
        with (folder / f"parts_{attempt:02}.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream))
    except OSError:
        return []
    return [folder / Path(row[0]).name for row in rows if len(row) == 3]


def graceful_stop(process):
    if process.poll() is not None:
        if process.stdin:
            process.stdin.close()
        return
    try:
        process.stdin.write(b"q\n")
        process.stdin.flush()
        process.wait(timeout=6)
    except OSError, subprocess.TimeoutExpired:
        terminate_tree(process)
    finally:
        if process.stdin:
            process.stdin.close()


def capture(identity, event):
    folder = inside(STORAGE / "live" / identity)
    folder.mkdir(parents=True, exist_ok=True)
    with Session() as session:
        item = session.get(LiveRecording, identity)
        options, url = dict(item.options), item.url
        min_free = settings(session)["min_free_gb"] * 1024**3
    started = time.monotonic()
    set_state(identity, status="connecting", started_at=now(), message="Подключение к эфиру")
    final_status, final_message, final_error = "finished", "Эфир завершён", None
    try:
        for attempt in range(4):
            if stopped(identity, event):
                final_status, final_message = "stopped", "Запись остановлена"
                break
            title, streams, identity_info = resolve_stream(url, options["height"])
            if stopped(identity, event):
                final_status, final_message = "stopped", "Запись остановлена"
                break
            set_state(
                identity,
                title=title,
                creator_name=identity_info["source_creator"],
                status="recording",
                message="Идёт запись; нарезки появятся после первой части",
            )
            command = capture_command(streams, folder, attempt, options["segment_seconds"])
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            last_bytes, last_growth = 0, time.monotonic()
            limit_reason = ""
            stalled = False
            try:
                while process.poll() is None:
                    register_parts(identity, closed_paths(folder, attempt))
                    size = sum(p.stat().st_size for p in folder.glob("capture_*.mkv"))
                    if size != last_bytes:
                        last_bytes, last_growth = size, time.monotonic()
                    if stopped(identity, event):
                        limit_reason = "Запись остановлена"
                    elif time.monotonic() - started >= options["max_hours"] * 3600:
                        limit_reason = "Достигнут лимит времени записи"
                    elif size >= options["max_gb"] * 1024**3:
                        limit_reason = "Достигнут лимит размера записи"
                    elif shutil.disk_usage(folder).free < min_free:
                        limit_reason = "Запись остановлена: мало свободного места"
                    elif time.monotonic() - last_growth > 45:
                        stalled = True
                    if limit_reason or stalled:
                        break
                    event.wait(0.5)
            finally:
                graceful_stop(process)
                register_parts(identity, folder.glob(f"capture_{attempt:02}_*.mkv"))
            if limit_reason:
                final_status, final_message = "stopped", limit_reason
                break
            if process.returncode == 0 and not stalled:
                break
            if attempt == 3:
                raise ValueError(
                    "Соединение потеряно. Выполнены 3 попытки переподключения; записанные части сохранены"
                )
            set_state(
                identity, status="reconnecting", message=f"Обрыв связи. Переподключение {attempt + 1}/3"
            )
            event.wait(3)
    except Exception as error:
        final_status, final_message, final_error = (
            "failed",
            "Запись прервана; сохранённые части доступны",
            str(error)[:500],
        )
    finally:
        set_state(
            identity,
            status=final_status,
            message=final_message,
            error=final_error,
            active_slot=None,
            finished_at=now(),
        )


def queue_parts():
    """Для одного эфира окна обрабатываются по порядку, даже при нескольких воркерах."""
    with Session() as session:
        jobs = session.scalars(select(RenderJob).where(RenderJob.kind == "live_clip")).all()
        busy = {j.options.get("live_id") for j in jobs if j.status in ("pending", "analyzing", "rendering")}
        for recording in session.scalars(
            select(LiveRecording).where(LiveRecording.clipping_enabled.is_(True))
        ):
            if recording.id in busy:
                continue
            # Сериализуем постановку с глобальной остановкой: после снятия флага
            # новые клипы не должны неожиданно появляться в очереди.
            locked = session.execute(
                update(LiveRecording)
                .where(LiveRecording.id == recording.id, LiveRecording.clipping_enabled.is_(True))
                .values(updated_at=LiveRecording.updated_at)
            )
            if not locked.rowcount:
                continue
            part = session.scalar(
                select(LiveSegment)
                .where(LiveSegment.recording_id == recording.id, LiveSegment.job_id.is_(None))
                .order_by(LiveSegment.start)
            )
            if not part:
                continue
            options = {
                **recording.options,
                "live_id": recording.id,
                "segment_id": part.id,
                "theme": recording.options.get("theme") or recording.title,
                "preset": "Gaming Viral",
            }
            job = RenderJob(kind="live_clip", options=options, message="Отбор моментов прямого эфира")
            session.add(job)
            session.flush()
            part.job_id = job.id
        session.commit()


def main():
    shutdown = multiprocessing.Event()
    signal.signal(signal.SIGTERM, lambda *_: shutdown.set())
    signal.signal(signal.SIGINT, lambda *_: shutdown.set())
    # После аварии не начинаем новую сетевую запись без действия пользователя.
    with Session() as session:
        interrupted = session.scalars(select(LiveRecording).where(LiveRecording.status.in_(ACTIVE[1:]))).all()
        for item in interrupted:
            item.status, item.active_slot, item.finished_at = "interrupted", None, now()
            item.message = "Приложение было закрыто. Сохранённые части доступны"
        session.commit()
    for item in interrupted:
        register_parts(item.id, (STORAGE / "live" / item.id).glob("capture_*.mkv"))
    child, child_stop, identity, stop_since = None, None, None, None
    try:
        while not shutdown.is_set():
            if child and not child.is_alive():
                child.join()
                with Session() as session:
                    item = session.get(LiveRecording, identity)
                    still_active = item and item.active_slot is not None
                if still_active:
                    register_parts(identity, (STORAGE / "live" / identity).glob("capture_*.mkv"))
                    set_state(
                        identity,
                        status="interrupted",
                        active_slot=None,
                        finished_at=now(),
                        message="Процесс записи завершился. Сохранённые части доступны",
                    )
                child = None
            if child:
                if stopped(identity, child_stop):
                    child_stop.set()
                    stop_since = stop_since or time.monotonic()
                    if time.monotonic() - stop_since > 12:
                        terminate_tree(child)
            else:
                with Session() as session:
                    for waiting in session.scalars(
                        select(LiveRecording).where(LiveRecording.status == "stopping")
                    ):
                        waiting.status, waiting.active_slot, waiting.finished_at = "stopped", None, now()
                    session.commit()
                    item = session.scalar(select(LiveRecording).where(LiveRecording.status == "pending"))
                    identity = item.id if item else None
                if identity:
                    child_stop = multiprocessing.Event()
                    child = multiprocessing.Process(target=capture, args=(identity, child_stop))
                    child.start()
                    stop_since = None
            queue_parts()
            shutdown.wait(1)
    finally:
        if child:
            child_stop.set()
            child.join(8)
            if child.is_alive():
                terminate_tree(child)
                child.join(3)
