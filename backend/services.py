"""Операции приложения между HTTP-слоем и базой данных."""

from sqlalchemy import select, update

from .database import settings
from .models import ContentProject, PublishJob, RenderJob, RenderedClip, SourceAsset, YouTubeChannel, now
from .schemas import RenderOptions


def create_jobs(session, options: RenderOptions):
    from .ads import snapshot
    from pathlib import Path

    assets = [session.get(SourceAsset, asset_id) for asset_id in options.asset_ids]
    if not assets or any(asset is None for asset in assets):
        raise ValueError("Выберите существующие исходники")
    if any(not asset.rights for asset in assets):
        raise ValueError("Для каждого исходника необходимо подтверждение прав")
    for asset in assets:
        active = session.scalar(
            select(RenderJob.id).where(
                RenderJob.asset_id == asset.id, RenderJob.status.in_(["pending", "analyzing", "rendering"])
            )
        )
        if active:
            raise ValueError(f"Исходник «{asset.name}» уже обрабатывается")
    if options.project_id and not session.get(ContentProject, options.project_id):
        raise ValueError("Проект не найден")
    saved = options.model_dump(exclude={"asset_ids", "project_id"})
    saved["ad_source"] = snapshot(session, duration=options.duration) if options.use_ads else None
    if options.layout == "split":
        secondary = (
            session.get(SourceAsset, options.secondary_asset_id) if options.secondary_asset_id else None
        )
        if not secondary or not secondary.rights or not Path(secondary.path).is_file():
            raise ValueError("Выберите нижний ролик с подтверждёнными правами")
        available = secondary.metadata_json["duration"] - options.secondary_start
        if available <= 0:
            raise ValueError("Начало нижнего ролика должно быть раньше его конца")
        if not options.secondary_loop and available < options.duration:
            raise ValueError("Нижний ролик слишком короткий. Включите повтор или уменьшите время начала")
        if secondary.id in options.asset_ids:
            raise ValueError("Для нижней половины выберите другой исходник")
        saved["split_source"] = dict(
            id=secondary.id, path=secondary.path, name=secondary.name, metadata=dict(secondary.metadata_json)
        )
    jobs = []
    for asset in assets:
        job = RenderJob(
            asset_id=asset.id,
            project_id=options.project_id,
            options=dict(saved),
        )
        session.add(job)
        jobs.append(job)
    from sqlalchemy.exc import IntegrityError

    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ValueError("Для выбранного исходника уже есть активное задание") from error
    notify_workers()
    return jobs


def notify_workers():
    # Redis ускоряет пробуждение; надёжная очередь всегда остаётся в SQL.
    from .config import REDIS_URL

    if REDIS_URL:
        try:
            import redis

            redis.Redis.from_url(REDIS_URL, socket_timeout=1).publish("clip-tribune:jobs", "wake")
        except Exception:
            pass


def claim_job(session, worker_id):
    candidate = session.scalar(
        select(RenderJob.id).where(RenderJob.status == "pending").order_by(RenderJob.created_at).limit(1)
    )
    if not candidate:
        return None
    # Compare-and-swap подходит и PostgreSQL, и SQLite. Два воркера не заберут одно задание.
    result = session.execute(
        update(RenderJob)
        .where(RenderJob.id == candidate, RenderJob.status == "pending")
        .values(status="analyzing", worker_id=worker_id, updated_at=now(), error=None)
    )
    session.commit()
    return session.get(RenderJob, candidate) if result.rowcount else None


def recover_jobs(session, stale_seconds=120):
    cutoff = now() - stale_seconds
    render_count = session.execute(
        update(RenderJob)
        .where(RenderJob.status.in_(["analyzing", "rendering"]), RenderJob.updated_at < cutoff)
        .values(status="failed", error="Воркер был прерван. Можно повторить задание.", finished_at=now())
    ).rowcount
    # URL resumable-сессии сохраняется; повтор начнётся с проверки состояния загрузки.
    session.execute(
        update(PublishJob)
        .where(PublishJob.status == "publishing", PublishJob.updated_at < cutoff)
        .values(status="pending", error="Продолжение после перезапуска")
    )
    session.commit()
    return render_count


def prepare_publish(session, request):
    config = settings(session)
    if request.privacy == "public" and not config["allow_public"]:
        raise ValueError("Сначала явно разрешите публичную публикацию в настройках")
    if request.channel_id and not session.get(YouTubeChannel, request.channel_id):
        raise ValueError("Канал не найден")
    clips = [session.get(RenderedClip, clip_id) for clip_id in request.clip_ids]
    if any(not clip for clip in clips):
        raise ValueError("Ролик не найден")
    jobs = []
    for clip in clips:
        asset = session.get(SourceAsset, clip.asset_id) if clip.asset_id else None
        if asset and not asset.rights:
            raise ValueError("Права на исходник не подтверждены")
        existing = session.scalar(select(PublishJob).where(PublishJob.clip_id == clip.id))
        if existing:
            jobs.append(existing)
            continue
        job = PublishJob(
            clip_id=clip.id,
            channel_id=request.channel_id,
            scheduled_at=request.scheduled_at,
            options=request.model_dump(exclude={"clip_ids", "channel_id", "scheduled_at"}),
        )
        session.add(job)
        jobs.append(job)
    session.commit()
    return jobs
