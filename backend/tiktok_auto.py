"""Экспериментальная отправка клипов эфира: по одному, с интервалом и лимитом.

Согласие даётся перед запуском записи. Ошибка приостанавливает отправку, но не запись.
"""

from sqlalchemy import select, update
from .database import Session
from .models import LiveRecording, RenderedClip, TikTokAccount, TikTokJob, now
from .schemas import TikTokPublishInput
from . import tiktok

POST_FIELDS = (
    "account_id",
    "privacy_level",
    "allow_comment",
    "allow_duet",
    "allow_stitch",
    "commercial",
    "brand_organic",
    "brand_content",
    "synthetic",
    "consent",
)


def request_for(config, clip_id="", title=""):
    caption = config.get("caption_template", "{title}").replace("{title}", title)
    # TikTok считает UTF-16; не разрываем эмодзи на границе длины.
    caption = caption.encode("utf-16-le")[:4400].decode("utf-16-le", errors="ignore")
    return TikTokPublishInput(
        clip_id=clip_id, mode="direct", title=caption, **{key: config[key] for key in POST_FIELDS}
    )


def validate_setup(session, config, duration):
    account = session.get(TikTokAccount, config["account_id"])
    if not account or not account.tokens or not config["consent"]:
        raise ValueError("Выберите аккаунт TikTok и разрешите автоматическую отправку")
    info = tiktok.creator_info(session, account)
    tiktok.validate_direct(request_for(config).model_dump(), info, duration)
    return info


def set_state(recording, **values):
    state = {**recording.options.get("tiktok_auto_state", {}), **values}
    recording.options = {**recording.options, "tiktok_auto_state": state}


def stop(session, recording, message="Автопубликация остановлена"):
    recording.auto_tiktok_enabled = False
    set_state(recording, message=message)
    for job in session.scalars(select(TikTokJob).where(TikTokJob.status.in_(["pending", "publishing"]))):
        if job.options.get("auto_live_id") == recording.id:
            job.status = "cancelled"
    session.commit()


def pause_failed(session, job, error):
    identity = job.options.get("auto_live_id")
    recording = session.get(LiveRecording, identity) if identity else None
    if recording and recording.auto_tiktok_enabled:
        recording.auto_tiktok_enabled = False
        set_state(recording, message="Автопубликация приостановлена после ошибки", error=error)


def claim_allowed(session, job):
    identity = job.options.get("auto_live_id")
    if not identity:
        return True
    recording = session.get(LiveRecording, identity)
    if not recording or not recording.auto_tiktok_enabled:
        job.status = "cancelled"
        session.commit()
        return False
    interval = recording.options["tiktok_auto"]["interval_minutes"] * 60
    set_state(recording, next_at=now() + interval, message="Отправляем клип в TikTok", error="")
    session.commit()
    return True


def queue_once():
    """После перезапуска сканирование восстанавливает очередь без повторов клипов."""
    with Session() as session:
        recordings = session.scalars(
            select(LiveRecording).where(LiveRecording.auto_tiktok_enabled.is_(True))
        ).all()
        for recording in recordings:
            try:
                queue_recording(session, recording)
            except Exception as error:
                session.rollback()
                session.refresh(recording)
                if recording.auto_tiktok_enabled:
                    recording.auto_tiktok_enabled = False
                    set_state(recording, message="Автопубликация приостановлена", error=str(error))
                    session.commit()


def queue_recording(session, recording):
    config = recording.options.get("tiktok_auto", {})
    state = recording.options.get("tiktok_auto_state", {})
    if not config.get("enabled"):
        return
    jobs = session.scalars(select(TikTokJob).where(TikTokJob.account_id == config["account_id"])).all()
    owned = [j for j in jobs if j.options.get("auto_live_id") == recording.id]
    failed = next(
        (
            j
            for j in owned
            if j.status in ("failed", "interrupted") and j.updated_at > state.get("ack_errors_before", 0)
        ),
        None,
    )
    if failed:
        pause_failed(session, failed, failed.error or "Проверьте результат предыдущей отправки")
        session.commit()
        return
    if any(j.status in ("pending", "publishing", "processing", "interrupted") for j in jobs):
        return
    if len(owned) >= config["max_posts"]:
        recording.auto_tiktok_enabled = False
        set_state(recording, message="Достигнут лимит автопубликаций этой записи", error="")
        session.commit()
        return
    if now() < state.get("next_at", 0):
        return
    recent = [j for j in jobs if j.created_at > now() - 86400 and j.status not in ("failed", "cancelled")]
    if len(recent) >= 15:
        recording.auto_tiktok_enabled = False
        set_state(recording, message="Локальный предел: 15 отправок на аккаунт за 24 часа", error="")
        session.commit()
        return
    used = {j.clip_id for j in jobs}
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
    info = validate_setup(session, config, clip.duration)
    # После сети берём короткую блокировку. Остановка либо запретит постановку,
    # либо дождётся commit и отменит уже помеченное автоматическое задание.
    locked = session.execute(
        update(LiveRecording)
        .where(LiveRecording.id == recording.id, LiveRecording.auto_tiktok_enabled.is_(True))
        .values(updated_at=now())
    )
    if not locked.rowcount:
        session.rollback()
        return
    tiktok.enqueue(session, request_for(config, clip.id, clip.title), creator=info, auto_live_id=recording.id)
