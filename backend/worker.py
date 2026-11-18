"""Отдельные процессы производства: главное окно никогда не выполняет FFmpeg.

Запуск: python -m backend.worker. На Windows multiprocessing использует spawn,
поэтому точка входа обязательно защищена условием __name__ == '__main__'.
"""

import json
import multiprocessing
import os
import shutil
import signal
import time
from pathlib import Path

import psutil
from sqlalchemy import select, update

from . import video
from .animation_engine import geometric_animation
from .config import REDIS_URL, STORAGE
from .database import Session, log, settings, update_settings
from .models import ClipCandidate, PublishJob, RenderJob, RenderedClip, Source, SourceAsset, now, uid
from .providers import HttpSpeechProvider, content_metadata, write_srt
from .schemas import PublishInput, RenderOptions
from .security import file_hash
from .services import claim_job, create_jobs, prepare_publish, recover_jobs
from .sources import download_media, import_file, remote_suffix
from .source_identity import creator_title
from .youtube import QuotaExceeded, search_trends, secret, upload


def cancellation_check(job_id):
    """Замыкание хранит частоту проверок, чтобы не читать SQL на каждом кадре."""
    last_check = [0.0]
    stopped = [False]

    def check():
        if time.monotonic() - last_check[0] < 0.5:
            return stopped[0]
        last_check[0] = time.monotonic()
        with Session() as session:
            job = session.get(RenderJob, job_id)
            stopped[0] = not job or job.status == "cancelled"
            if job and not stopped[0]:
                job.updated_at = now()
                session.commit()
        return stopped[0]

    return check


def process_job(job_id):
    started = time.monotonic()
    cancelled = cancellation_check(job_id)
    with Session() as session:
        job = session.get(RenderJob, job_id)
        config = settings(session)
        options = {**config, **job.options}
        analysis_seconds = 0
        render_seconds = 0
        try:
            if shutil.disk_usage(STORAGE).free < config["min_free_gb"] * 1024**3:
                raise ValueError("Недостаточно свободного места на диске")
            if job.kind == "download":
                from tempfile import TemporaryDirectory
                from .downloads import download

                def progress(data):
                    # Обновляем только прогресс, чтобы не перезаписать статус отмены.
                    session.execute(
                        update(RenderJob)
                        .where(RenderJob.id == job.id, RenderJob.status != "cancelled")
                        .values(progress=data["progress"], message=data["message"], updated_at=now())
                    )
                    session.commit()

                job.message = "Получение информации о видео"
                session.commit()
                with TemporaryDirectory(dir=STORAGE / "temp") as folder:
                    target, title, identity_info = download(
                        job.options["url"], job.options["height"], folder, cancelled, progress
                    )
                    if cancelled():
                        raise video.Cancelled()
                    asset = import_file(session, target, True)
                    asset.name = title + target.suffix
                    asset.metadata_json = {**asset.metadata_json, **identity_info}
                    session.commit()
                job.message = "Скачано: " + asset.name + ". Видео доступно в разделе «Источники»."
            elif job.kind in ("live_clip", "live_export"):
                from .live_clips import process as process_live, export as export_live

                if job.kind == "live_clip":
                    process_live(session, job, options, cancelled)
                else:
                    export_live(session, job, cancelled)
            elif job.kind == "import_remote":
                target = STORAGE / "temp" / (uid() + remote_suffix(job.options["url"]))
                try:
                    download_media(job.options["url"], target)
                    import_file(session, target, job.options["rights"])
                finally:
                    target.unlink(missing_ok=True)
            elif job.kind == "demo":
                target = STORAGE / "temp" / (uid() + ".mp4")
                try:
                    video.make_test_video(target)
                    asset = import_file(session, target, True)
                    asset.name = "Тестовый исходник FFmpeg.mp4"
                    session.commit()
                    existing = session.scalar(
                        select(RenderedClip.id).where(RenderedClip.asset_id == asset.id)
                    )
                    if not existing:
                        create_jobs(
                            session,
                            RenderOptions(
                                asset_ids=[asset.id], theme="Тестовый видеосигнал", count=2, duration=15
                            ),
                        )
                    job.message = "Тестовый исходник готов. Результаты доступны в библиотеке или очереди."
                finally:
                    target.unlink(missing_ok=True)
            elif job.kind == "ad_overlay":
                original = session.get(RenderedClip, job.options["clip_id"])
                if not original or not Path(original.path).is_file():
                    raise ValueError("Исходный ролик для рекламы больше не найден")
                job.status, job.message, job.progress = "rendering", "Наложение рекламы на копию ролика", 20
                session.commit()
                output = STORAGE / "clips" / (uid() + ".mp4")
                selected = dict(
                    start=0,
                    duration=original.duration,
                    score=original.score,
                    reasons=["Рекламная вставка; оригинал сохранён в библиотеке"],
                )
                render_start = time.monotonic()
                video.render(original.path, output, selected, options, video.probe(original.path), cancelled)
                render_seconds = time.monotonic() - render_start
                save_clip(
                    session,
                    job,
                    session.get(SourceAsset, original.asset_id) if original.asset_id else None,
                    None,
                    output,
                    selected,
                    "",
                    source_clip=original,
                )
                job.message = "Создана отдельная копия с рекламой"
            elif job.kind == "animation":
                output = STORAGE / "clips" / (uid() + ".mp4")
                geometric_animation(output, cancelled)
                candidate = dict(
                    start=0, duration=15, score=0, reasons=["Процедурная геометрическая анимация"]
                )
                save_clip(session, job, None, None, output, candidate, "Геометрические персонажи")
                job.message = "Анимация создана"
            else:
                asset = session.get(SourceAsset, job.asset_id)
                if not asset or not asset.rights:
                    raise ValueError("Исходник отсутствует или права не подтверждены")
                job.message = "Анализ движения, сцен и звуковых пиков"
                job.progress = 5
                session.commit()
                analysis_start = time.monotonic()
                features = video.analyze(asset.path, asset.metadata_json, cancelled)
                analysis_seconds = time.monotonic() - analysis_start
                # Учитываем только кандидатов, для которых реально сохранён клип.
                previous = session.scalars(
                    select(ClipCandidate)
                    .join(RenderedClip, RenderedClip.candidate_id == ClipCandidate.id)
                    .where(ClipCandidate.asset_id == asset.id)
                ).all()
                used = [dict(start=c.start, duration=c.duration, fingerprint=c.fingerprint) for c in previous]
                selected = video.select_candidates(
                    features,
                    asset.metadata_json["duration"],
                    options["duration"],
                    options["count"],
                    used,
                    options.get("min_score", 0),
                    options["preset"],
                )
                if not selected:
                    raise ValueError("Нет новых неповторяющихся фрагментов нужной длительности и оценки")
                transcript = []
                warning = ""
                if options.get("subtitles"):
                    if secret("SPEECH_API_URL"):
                        try:
                            transcript = HttpSpeechProvider().transcribe(asset.path)
                        except Exception:
                            warning = "Распознавание недоступно; экспорт без субтитров"
                    else:
                        warning = "SpeechProvider не настроен; экспорт без субтитров"
                for index, selected_candidate in enumerate(selected):
                    if cancelled():
                        raise video.Cancelled()
                    job.status = "rendering"
                    job.message = f"Рендеринг {index + 1} из {len(selected)}. {warning}"
                    job.progress = 25 + index / len(selected) * 70
                    session.commit()
                    candidate = ClipCandidate(asset_id=asset.id, **selected_candidate)
                    session.add(candidate)
                    session.commit()
                    output = STORAGE / "clips" / (uid() + ".mp4")
                    srt = output.with_suffix(".srt")
                    has_srt = (
                        write_srt(transcript, candidate.start, candidate.duration, srt)
                        if transcript
                        else False
                    )
                    render_start = time.monotonic()
                    video.render(
                        asset.path,
                        output,
                        selected_candidate,
                        options,
                        asset.metadata_json,
                        cancelled,
                        srt if has_srt else None,
                    )
                    render_seconds += time.monotonic() - render_start
                    save_clip(
                        session,
                        job,
                        asset,
                        candidate,
                        output,
                        selected_candidate,
                        options.get("theme", ""),
                        warning,
                        transcript,
                    )
                job.message = f"Готово: {len(selected)} ролик(а). {warning}"
            if cancelled():
                raise video.Cancelled()
            job.status = "ready"
            job.progress = 100
            job.finished_at = now()
            job.metrics = dict(
                analysis_seconds=round(analysis_seconds, 2),
                render_seconds=round(render_seconds, 2),
                total_seconds=round(time.monotonic() - started, 2),
            )
            session.commit()
            log(session, f"Задание {job.id[:8]} завершено")
        except video.Cancelled:
            session.rollback()
            job = session.get(RenderJob, job_id)
            job.status, job.message, job.finished_at = "cancelled", "Обработка отменена", now()
            session.commit()
        except Exception as error:
            session.rollback()
            job = session.get(RenderJob, job_id)
            job.status, job.error, job.finished_at = "failed", str(error)[:2000], now()
            session.commit()
            log(session, f"Задание {job.id[:8]}: {job.error}", "error")


def save_clip(
    session,
    job,
    asset,
    candidate,
    output,
    selected,
    theme,
    warning="",
    transcript=(),
    source_clip=None,
    source_name=None,
    metadata_extra=None,
):
    metadata = (
        dict(source_clip.metadata_json)
        if source_clip
        else content_metadata(
            theme,
            asset.name if asset else (source_name or "Оригинальная анимация"),
            selected,
            " ".join(
                s["text"]
                for s in transcript
                if selected["start"] <= s["start"] < selected["start"] + selected["duration"]
            ),
        )
    )
    if source_clip:
        metadata["titles"] = [source_clip.title + " · реклама"]
        metadata["source_clip_id"] = source_clip.id
    metadata.update(
        reasons=selected["reasons"],
        subtitle_status=warning,
        start=selected["start"],
        render_options=job.options,
    )
    if metadata_extra:
        metadata.update(metadata_extra)
    # Автор относится к исходнику, а не к аккаунту, куда отправляется клип.
    # Явное название сохраняется даже при подключённом AI-генераторе заголовков.
    if asset and not source_clip:
        metadata.update(
            {
                k: asset.metadata_json[k]
                for k in ("source_platform", "source_creator", "source_url")
                if k in asset.metadata_json
            }
        )
    if not source_clip and (title := creator_title(metadata)):
        metadata["titles"] = [title]
    thumb = output.with_suffix(".png")
    video.thumbnail(output, thumb)
    clip = RenderedClip(
        job_id=job.id,
        asset_id=asset.id if asset else None,
        candidate_id=candidate.id if candidate else None,
        title=metadata["titles"][0],
        path=str(output),
        thumbnail=str(thumb),
        duration=video.probe(output)["duration"],
        size=output.stat().st_size,
        score=selected["score"],
        metadata_json=metadata,
        sha256=file_hash(output),
    )
    session.add(clip)
    session.commit()
    config = settings(session)
    if config["output_folder"]:
        # Пользователь явно выбирает эту папку в настройках. Имена уникальны.
        folder = Path(config["output_folder"]).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(output, folder / output.name)
    if job.options.get("automatic") and config["auto_queue"]:
        prepare_publish(
            session, PublishInput(clip_ids=[clip.id], channel_id=config["auto_channel_id"] or None)
        )


def publish_once():
    with Session() as session:
        config = settings(session)
        if not config["publishing_enabled"]:
            return
        waiting = session.scalars(
            select(PublishJob)
            .where(
                PublishJob.status == "pending",
                PublishJob.channel_id.is_not(None),
                (PublishJob.scheduled_at.is_(None)) | (PublishJob.scheduled_at <= now()),
            )
            .order_by(PublishJob.created_at)
        ).all()
        job = next(
            (
                item
                for item in waiting
                if not item.options.get("auto_live_id")
                and (item.options.get("approved") or config["auto_publish"])
            ),
            None,
        )
        if not job:
            return
        claimed = session.execute(
            update(PublishJob)
            .where(PublishJob.id == job.id, PublishJob.status == "pending")
            .values(status="publishing", updated_at=now())
        )
        session.commit()
        if not claimed.rowcount:
            return
        job.status = "publishing"
        job.attempts += 1
        session.commit()
        job_id = job.id

        def stopped():
            with Session() as other:
                live = other.get(PublishJob, job_id)
                if live:
                    live.updated_at = now()
                    other.commit()
                return not live or live.status == "cancelled" or not settings(other)["publishing_enabled"]

        try:
            clip = session.get(RenderedClip, job.clip_id)
            if job.options.get("privacy") == "public" and not config["allow_public"]:
                raise ValueError("Публичная публикация отключена в настройках")
            job.video_id = upload(session, job, clip, stopped)
            job.status, job.progress, job.finished_at = "published", 100, now()
            job.error = None
            clip.status = "published"
            session.commit()
        except QuotaExceeded as error:
            job.status, job.error = "pending", str(error)
            session.commit()
            update_settings(session, {"publishing_enabled": False})
        except video.Cancelled:
            session.refresh(job)
            if job.status != "cancelled":
                job.status = "pending"
            session.commit()
        except Exception as error:
            # Повторные сетевые попытки ограничены и отложены, URL сессии сохранён.
            job.error = str(error)[:1000]
            if job.attempts < 5 and job.upload_url:
                job.status = "pending"
                job.scheduled_at = now() + min(300, 2**job.attempts * 5)
            else:
                job.status, job.finished_at = "failed", now()
            session.commit()


def scheduler_tick(observed):
    with Session() as session:
        config = settings(session)
        for source in session.scalars(select(Source).where(Source.watching.is_(True))):
            folder = Path(source.path)
            if not folder.is_dir():
                continue
            for path in folder.iterdir():
                if path.suffix.lower() not in (".mp4", ".mov", ".mkv", ".webm") or not path.is_file():
                    continue
                key = str(path)
                signature = (path.stat().st_size, path.stat().st_mtime)
                old = observed.get(key)
                observed[key] = signature
                # Два одинаковых наблюдения: файл перестал копироваться.
                if old != signature or observed.get(key + ":done") == signature:
                    continue
                try:
                    import_file(session, path, source.rights, source.id)
                except Exception as error:
                    log(session, f"Импорт {path.name}: {error}", "error")
                observed[key + ":done"] = signature
        if config["production"] == "running":
            for asset in session.scalars(select(SourceAsset).where(SourceAsset.rights.is_(True))):
                existing = session.scalar(select(RenderJob.id).where(RenderJob.asset_id == asset.id).limit(1))
                if existing:
                    continue
                jobs = create_jobs(
                    session,
                    RenderOptions(
                        asset_ids=[asset.id],
                        count=config["auto_count"],
                        duration=config["auto_duration"],
                        theme=config["auto_theme"],
                        preset=config["auto_preset"],
                        min_score=config["auto_min_score"],
                        resolution=config["resolution"],
                        framing=config["framing"],
                    ),
                )
                for job in jobs:
                    job.options = {**job.options, "automatic": True}
                session.commit()
        interval = config["trend_interval_minutes"]
        if interval and config["trend_query"] and now() - config["trend_last_run"] >= max(15, interval) * 60:
            update_settings(session, {"trend_last_run": now()})
            try:
                search_trends(session, config["trend_query"], config["trend_region"], config["trend_hours"])
            except Exception as error:
                log(session, f"Обновление трендов: {error}", "error")
        recover_jobs(session)


def worker_loop(slot, shutdown):
    worker_id = f"{os.getpid()}-{slot}"
    subscription = None
    if REDIS_URL:
        try:
            import redis

            subscription = redis.Redis.from_url(REDIS_URL, socket_timeout=2).pubsub()
            subscription.subscribe("clip-tribune:jobs")
        except Exception:
            subscription = None
    while not shutdown.is_set():
        with Session() as session:
            config = settings(session)
            job = None if config.get("queue_paused") else claim_job(session, worker_id)
        if job:
            process_job(job.id)
        elif subscription:
            try:
                subscription.get_message(timeout=1)
            except Exception:
                subscription.close()
                subscription = None
        else:
            shutdown.wait(1)


def main():
    shutdown = multiprocessing.Event()
    signal.signal(signal.SIGTERM, lambda *_: shutdown.set())
    signal.signal(signal.SIGINT, lambda *_: shutdown.set())
    children = []
    observed = {}
    last_tick = 0
    heartbeat = STORAGE / "worker.json"
    try:
        while not shutdown.is_set():
            with Session() as session:
                desired = settings(session)["workers"]
            children = [child for child in children if child.is_alive()]
            while len(children) < desired:
                child = multiprocessing.Process(target=worker_loop, args=(len(children), shutdown))
                child.start()
                children.append(child)
            # Уменьшение параллелизма применяется после перезапуска, не убивает рендер.
            heartbeat.write_text(
                json.dumps(
                    dict(
                        pid=os.getpid(),
                        time=now(),
                        workers=len(children),
                        cpu=psutil.cpu_percent(),
                        memory_mb=round(psutil.virtual_memory().used / 1024**2),
                        free_gb=round(shutil.disk_usage(STORAGE).free / 1024**3, 1),
                    )
                ),
                encoding="utf-8",
            )
            if time.monotonic() - last_tick > 10:
                try:
                    scheduler_tick(observed)
                except Exception as error:
                    with Session() as session:
                        log(session, f"Планировщик: {error}", "error")
                last_tick = time.monotonic()
            publish_once()
            from .youtube_auto import tick as youtube_auto_tick

            try:
                youtube_auto_tick()
            except Exception as error:
                with Session() as session:
                    log(session, f"Автопубликация YouTube: {error}", "error")
            from .tiktok import tick as tiktok_tick

            try:
                tiktok_tick()
            except Exception as error:
                with Session() as session:
                    log(session, f"TikTok: {error}", "error")
            shutdown.wait(1)
    finally:
        shutdown.set()
        for child in children:
            child.join(5)
            if child.is_alive():
                child.terminate()
                child.join()
        heartbeat.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
