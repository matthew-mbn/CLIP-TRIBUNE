"""Независимая серия YouTube. Не запускает накопленную ручную очередь публикации."""

import httpx
from sqlalchemy import select, update
from .database import Session, settings
from .models import LiveRecording, PublishJob, RenderedClip, YouTubeChannel, now
from .security import inside
from . import youtube, video


def set_state(recording, **values):
    # Отдельная колонка: обновление YouTube не затирает состояние TikTok.
    recording.youtube_auto_state = {**(recording.youtube_auto_state or {}), **values}


def validate_setup(session, config):
    channel = session.get(YouTubeChannel, config.get("channel_id", ""))
    if not config.get("consent") or not channel or not channel.tokens:
        raise ValueError("Выберите подключённый канал YouTube и разрешите автоматическую отправку")
    if config["privacy"] == "public" and not settings(session)["allow_public"]:
        raise ValueError("Для YouTube сначала разрешите публичную публикацию в настройках")


def stop(session, recording):
    recording.auto_youtube_enabled = False
    set_state(recording, message="Автопубликация остановлена")
    for job in session.scalars(select(PublishJob).where(PublishJob.status.in_(["pending", "publishing"]))):
        if job.options.get("auto_live_id") == recording.id:
            job.status, job.finished_at = "cancelled", now()
    session.commit()


def enabled(session, job):
    recording = session.get(LiveRecording, job.options.get("auto_live_id", ""))
    return bool(recording and recording.auto_youtube_enabled)


def queue_recording(session, recording):
    config = recording.options.get("youtube_auto", {})
    if not config.get("enabled"):
        return
    state = recording.youtube_auto_state or {}
    all_jobs = session.scalars(select(PublishJob)).all()
    owned = [j for j in all_jobs if j.options.get("auto_live_id") == recording.id]
    failed = next(
        (j for j in owned if j.status == "failed" and j.updated_at > state.get("ack_errors_before", 0)), None
    )
    if failed:
        raise ValueError(failed.error or "Проверьте результат отправки YouTube")
    if any(j.status in ("pending", "publishing") for j in owned):
        return
    if len(owned) >= config["max_posts"]:
        recording.auto_youtube_enabled = False
        set_state(recording, message="Достигнут лимит отправок этой записи", error="")
        session.commit()
        return
    if now() < state.get("next_at", 0):
        return
    used = {j.clip_id for j in all_jobs}
    clip = next(
        (
            c
            for c in session.scalars(select(RenderedClip).order_by(RenderedClip.created_at))
            if c.metadata_json.get("live_id") == recording.id and c.id not in used
        ),
        None,
    )
    if not clip:
        return
    validate_setup(session, config)
    if not inside(clip.path).is_file():
        raise ValueError("Файл ролика не найден")
    locked = session.execute(
        update(LiveRecording)
        .where(LiveRecording.id == recording.id, LiveRecording.auto_youtube_enabled.is_(True))
        .values(updated_at=now())
    )
    if not locked.rowcount:
        session.rollback()
        return
    session.add(
        PublishJob(
            clip_id=clip.id,
            channel_id=config["channel_id"],
            options={
                "auto_live_id": recording.id,
                **{
                    key: config[key]
                    for key in ("privacy", "synthetic", "made_for_kids", "paid_product_placement")
                },
            },
        )
    )
    session.commit()


def queue_once():
    with Session() as session:
        for recording in session.scalars(
            select(LiveRecording).where(LiveRecording.auto_youtube_enabled.is_(True))
        ).all():
            try:
                queue_recording(session, recording)
            except Exception as error:
                session.rollback()
                session.refresh(recording)
                if recording.auto_youtube_enabled:
                    recording.auto_youtube_enabled = False
                    set_state(recording, message="Автопубликация приостановлена", error=str(error))
                    session.commit()


def tick():
    queue_once()
    with Session() as session:
        job = next(
            (
                j
                for j in session.scalars(
                    select(PublishJob)
                    .where(
                        PublishJob.status == "pending",
                        PublishJob.scheduled_at.is_(None) | (PublishJob.scheduled_at <= now()),
                    )
                    .order_by(PublishJob.created_at)
                )
                if j.options.get("auto_live_id") and enabled(session, j)
            ),
            None,
        )
        if not job:
            return
        changed = session.execute(
            update(PublishJob)
            .where(PublishJob.id == job.id, PublishJob.status == "pending")
            .values(status="publishing", updated_at=now())
        )
        session.commit()
        if not changed.rowcount:
            return
        recording = session.get(LiveRecording, job.options["auto_live_id"])
        set_state(
            recording,
            next_at=now() + recording.options["youtube_auto"]["interval_minutes"] * 60,
            message="Отправляем клип в YouTube",
            error="",
        )
        job.attempts += 1
        session.commit()

        def stopped():
            with Session() as other:
                current = other.get(PublishJob, job.id)
                if not current or current.status == "cancelled" or not enabled(other, current):
                    return True
                current.updated_at = now()
                other.commit()
                return False

        try:
            validate_setup(session, recording.options["youtube_auto"])
            if job.options.get("privacy") == "public" and not settings(session)["allow_public"]:
                raise ValueError("Публичная публикация отключена в настройках")
            clip = session.get(RenderedClip, job.clip_id)
            identity = youtube.upload(session, job, clip, stopped)
            session.refresh(job)
            # Даже при остановке сохраняем полученный ID: удалять принятый пост нельзя.
            job.video_id = identity
            job.status, job.progress, job.finished_at = "published", 100, now()
            job.error = None
            session.commit()
        except video.Cancelled:
            session.refresh(job)
            job.status, job.finished_at = "cancelled", now()
            session.commit()
        except Exception as error:
            session.rollback()
            session.refresh(job)
            session.refresh(recording)
            if job.status == "cancelled":
                return
            # Сетевые исключения могут включать секретный URL resumable-сессии.
            detail = (
                f"Ошибка соединения YouTube ({type(error).__name__})"
                if isinstance(error, httpx.RequestError)
                else str(error)[:1000]
            )
            job.status, job.error, job.updated_at = "failed", detail, now()
            recording.auto_youtube_enabled = False
            set_state(recording, message="Автопубликация приостановлена после ошибки", error=detail)
            session.commit()
