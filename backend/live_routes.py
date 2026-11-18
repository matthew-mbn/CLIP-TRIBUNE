"""Короткие HTTP-команды для записи: сетевой захват работает в другой службе."""

from pathlib import Path
from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .config import STORAGE
from .database import Session, public, update_settings
from .models import LiveRecording, LiveSegment, RenderJob, RenderedClip, TikTokJob, now
from .schemas import LiveInput
from .security import inside

router = APIRouter(prefix="/api/live")


def required(session, identity):
    item = session.get(LiveRecording, identity)
    if not item:
        raise ValueError("Запись эфира не найдена")
    return item


@router.get("")
def recordings():
    with Session() as session:
        jobs = session.scalars(
            select(RenderJob).where(RenderJob.kind.in_(["live_clip", "live_export"]))
        ).all()
        clips = session.scalars(select(RenderedClip)).all()
        result = []
        for item in session.scalars(select(LiveRecording).order_by(LiveRecording.created_at.desc())):
            job_ids = {job.id for job in jobs if job.options.get("live_id") == item.id}
            result.append(
                {
                    **public(item),
                    "clips": sum(c.job_id in job_ids for c in clips),
                    "waiting": sum(
                        j.id in job_ids and j.status in ("pending", "analyzing", "rendering") for j in jobs
                    ),
                }
            )
        return result


@router.post("")
def start(request: LiveInput):
    from .live import validate_live_url
    from .ads import snapshot

    if not request.rights:
        raise ValueError("Подтвердите право на запись и использование эфира")
    url, platform = validate_live_url(request.url)
    with Session() as session:
        if session.scalar(select(LiveRecording.id).where(LiveRecording.active_slot == 1)):
            raise ValueError("Уже идёт запись. Сначала остановите текущий эфир")
        options = request.model_dump(exclude={"url", "rights"})
        options["ad_source"] = snapshot(session, duration=request.duration) if request.use_ads else None
        if request.tiktok_auto.enabled:
            from .tiktok_auto import validate_setup

            if options["ad_source"] and not request.tiktok_auto.commercial:
                raise ValueError(
                    "Для автопубликации роликов с рекламой включите раскрытие коммерческого контента"
                )
            validate_setup(session, options["tiktok_auto"], request.duration)
        item = LiveRecording(
            url=url,
            platform=platform,
            active_slot=1,
            options=options,
            clipping_enabled=request.auto_clip,
            auto_tiktok_enabled=request.tiktok_auto.enabled,
        )
        session.add(item)
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise ValueError("Другой эфир уже запускается") from error
        if request.auto_clip:
            update_settings(session, {"queue_paused": False})
        return public(item)


@router.post("/{identity}/stop")
def stop(identity: str):
    with Session() as session:
        item = required(session, identity)
        from .tiktok_auto import stop as stop_auto

        stop_auto(session, item)
        if item.active_slot is not None:
            if item.status == "pending":
                item.status, item.active_slot, item.finished_at = "stopped", None, now()
            else:
                item.status = "stopping"
            item.message = "Остановка записи; готовые части и нарезки сохраняются"
            session.commit()
        return public(item)


@router.get("/{identity}/location")
def location(identity: str):
    with Session() as session:
        required(session, identity)
    folder = inside(STORAGE / "live" / identity)
    folder.mkdir(parents=True, exist_ok=True)
    return {"path": str(folder)}


@router.post("/{identity}/export")
def export(identity: str):
    with Session() as session:
        item = required(session, identity)
        if item.active_slot is not None:
            raise ValueError("Для сборки всей записи сначала остановите эфир")
        parts = session.scalars(select(LiveSegment).where(LiveSegment.recording_id == identity)).all()
        if not parts or not all(Path(p.path).is_file() for p in parts):
            raise ValueError("Нет сохранённых частей записи")
        for job in session.scalars(select(RenderJob).where(RenderJob.kind == "live_export")):
            if job.options.get("live_id") == identity and job.status in ("pending", "analyzing", "rendering"):
                return public(job)
        job = RenderJob(kind="live_export", options={"live_id": identity}, message="Сборка записи эфира")
        session.add(job)
        session.commit()
        return public(job)


def stop_all(session):
    """Глобальная остановка отключает также ещё не поставленные в очередь нарезки."""
    for item in session.scalars(select(LiveRecording)):
        item.clipping_enabled = False
        item.auto_tiktok_enabled = False
        if item.active_slot is not None:
            item.status = "stopping"
            item.message = "Остановка всех задач"
    session.commit()


@router.post("/{identity}/tiktok/{action}")
def tiktok_control(identity: str, action: str):
    from .tiktok_auto import stop as stop_auto, validate_setup, set_state

    with Session() as session:
        item = required(session, identity)
        if action == "stop":
            stop_auto(session, item)
        elif action == "resume":
            config = item.options.get("tiktok_auto", {})
            if not config.get("enabled"):
                raise ValueError("Автопубликация не была включена для этой записи")
            if session.scalar(
                select(TikTokJob.id).where(
                    TikTokJob.account_id == config["account_id"], TikTokJob.status == "interrupted"
                )
            ):
                raise ValueError("Сначала проверьте статус прерванной отправки в разделе TikTok")
            validate_setup(session, config, item.options["duration"])
            item.auto_tiktok_enabled = True
            set_state(item, message="Автопубликация включена", error="", ack_errors_before=now())
            session.commit()
        else:
            raise ValueError("Неизвестная команда TikTok")
        return public(item)
