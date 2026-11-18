"""REST API CLIP TRIBUNE. Обработчики проверяют ввод и вызывают сервисы.

Тяжёлые операции рендеринга выполняет backend.worker. Tkinter получает прогресс
через короткие HTTP-запросы, поэтому интерфейс и движок можно изучать отдельно.
"""

import json
import secrets
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import youtube
from .config import FFMPEG, FFPROBE, STORAGE, MAX_UPLOAD
from .database import Session, public, settings, update_settings
from .models import (
    ActivityLog,
    ContentProject,
    PublishJob,
    RenderJob,
    RenderedClip,
    Source,
    SourceAsset,
    TrendRecord,
    YouTubeChannel,
    TikTokJob,
    now,
    uid,
)
from .schemas import FolderInput, PublishInput, RemoteInput, RenderOptions, SettingsInput, TrendInput
from .schemas import DownloadInput
from .security import encrypt, inside
from .services import create_jobs, prepare_publish
from .sources import import_file
from .video import run
from .tiktok_routes import router as tiktok_router
from .ads_routes import router as ads_router
from .live_routes import router as live_router
from .webcam_routes import router as webcam_router

token_path = STORAGE / ".api-token"
if not token_path.exists():
    try:
        with token_path.open("x", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(48))
    except FileExistsError:
        pass
LOCAL_TOKEN = token_path.read_text(encoding="utf-8")

app = FastAPI(
    title="CLIP TRIBUNE", version="0.5.0", description="Локальная студия автоматического видеомонтажа"
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.include_router(tiktok_router)
app.include_router(ads_router)
app.include_router(live_router)
app.include_router(webcam_router)


@app.middleware("http")
async def local_access(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path not in (
        "/api/health",
        "/api/youtube/callback",
        "/api/tiktok/callback",
    ):
        supplied = request.headers.get("X-Clip-Tribune", "")
        if not secrets.compare_digest(supplied, LOCAL_TOKEN):
            return JSONResponse({"detail": "Требуется локальный ключ приложения"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin not in ("http://127.0.0.1:8765", "http://localhost:8765"):
            return JSONResponse({"detail": "Внешний Origin запрещён"}, status_code=403)
    return await call_next(request)


@app.exception_handler(ValueError)
async def invalid_request(_, error):
    return JSONResponse({"detail": str(error)}, status_code=400)


@app.exception_handler(RuntimeError)
async def integration_error(_, error):
    return JSONResponse({"detail": str(error)}, status_code=502)


@app.exception_handler(youtube.QuotaExceeded)
async def quota_error(_, error):
    return JSONResponse({"detail": str(error)}, status_code=429)


def required(session, model, identity):
    item = session.get(model, identity)
    if not item:
        raise HTTPException(404, "Запись не найдена")
    return item


@app.get("/api/health")
def health():
    return {"name": "CLIP TRIBUNE", "status": "ok"}


@app.get("/api/dashboard")
def dashboard():
    with Session() as session:

        def count(model, *conditions):
            return session.scalar(select(func.count()).select_from(model).where(*conditions))

        heartbeat = {}
        try:
            heartbeat = json.loads((STORAGE / "worker.json").read_text(encoding="utf-8"))
            heartbeat["alive"] = now() - heartbeat["time"] < 120
        except OSError, ValueError:
            heartbeat = {"alive": False}
        from datetime import datetime

        midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        completed = session.scalars(
            select(RenderJob).where(RenderJob.status == "ready", RenderJob.kind == "clips")
        ).all()
        total_seconds = sum(job.metrics.get("total_seconds", 0) for job in completed)
        clips = count(RenderedClip)
        return dict(
            sources=count(SourceAsset),
            trends=count(TrendRecord),
            processing=count(RenderJob, RenderJob.status.in_(["analyzing", "rendering"])),
            queued=count(RenderJob, RenderJob.status == "pending"),
            ready=count(RenderedClip, RenderedClip.status == "ready"),
            today=count(RenderedClip, RenderedClip.created_at >= midnight),
            published=count(PublishJob, PublishJob.status == "published")
            + count(TikTokJob, TikTokJob.status == "published"),
            errors=count(RenderJob, RenderJob.status == "failed"),
            worker=heartbeat,
            clips_per_hour=round(clips / total_seconds * 3600, 1) if total_seconds else None,
            production=settings(session)["production"],
            queue_paused=settings(session).get("queue_paused", False),
            logs=[
                public(row)
                for row in session.scalars(
                    select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(30)
                )
            ],
        )


@app.get("/api/settings")
def get_settings():
    with Session() as session:
        result = settings(session)
        result.pop("secrets", None)
        result["configured"] = {
            name: bool(youtube.secret(name))
            for name in (
                "YOUTUBE_API_KEY",
                "GOOGLE_CLIENT_ID",
                "GOOGLE_CLIENT_SECRET",
                "TIKTOK_CLIENT_KEY",
                "TIKTOK_CLIENT_SECRET",
                "AI_API_URL",
                "AI_API_KEY",
                "AI_MODEL",
                "SPEECH_API_URL",
                "SPEECH_API_KEY",
            )
        }
        return result


@app.put("/api/settings")
def save_settings(request: SettingsInput):
    with Session() as session:
        values = request.model_dump(exclude_unset=True)
        if "auto_preset" in values:
            RenderOptions(preset=values["auto_preset"])
        if "auto_publish" in values:
            values["publishing_enabled"] = values["auto_publish"]
        update_settings(session, values)
        return {"saved": True}


class SecretInput(BaseModel):
    values: dict[str, str]


@app.put("/api/settings/secrets")
def save_secrets(request: SecretInput):
    allowed = {
        "YOUTUBE_API_KEY",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "TIKTOK_CLIENT_KEY",
        "TIKTOK_CLIENT_SECRET",
        "AI_API_URL",
        "AI_API_KEY",
        "AI_MODEL",
        "SPEECH_API_URL",
        "SPEECH_API_KEY",
    }
    if set(request.values) - allowed:
        raise ValueError("Неизвестный параметр интеграции")
    with Session() as session:
        stored = settings(session).get("secrets", {})
        for key, value in request.values.items():
            if value:
                stored[key] = encrypt(value)
            else:
                stored.pop(key, None)
        update_settings(session, {"secrets": stored})
    return {"saved": True}


@app.get("/api/diagnostics")
def diagnostics():
    result = {
        "ffmpeg": False,
        "ffprobe": False,
        "encoders": [],
        "storage": str(STORAGE),
        "free_gb": round(shutil.disk_usage(STORAGE).free / 1024**3, 1),
    }
    for key, binary in [("ffmpeg", FFMPEG), ("ffprobe", FFPROBE)]:
        try:
            result[key] = run([binary, "-version"], timeout=10).splitlines()[0]
        except (OSError, RuntimeError) as error:
            result[key + "_error"] = str(error)
    if result["ffmpeg"]:
        encoders = run([FFMPEG, "-hide_banner", "-encoders"], timeout=10)
        result["encoders"] = [e for e in ("libx264", "h264_nvenc", "h264_qsv", "h264_amf") if e in encoders]
    return result


@app.get("/api/sources")
def sources():
    with Session() as session:
        return {
            "assets": [
                public(row)
                for row in session.scalars(select(SourceAsset).order_by(SourceAsset.created_at.desc()))
            ],
            "folders": [dict(public(row), path=row.path) for row in session.scalars(select(Source))],
        }


class LocalImport(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=100)
    rights: bool = False


@app.post("/api/sources/local")
def import_local(request: LocalImport):
    results, errors = [], []
    with Session() as session:
        for path in request.paths:
            try:
                results.append(public(import_file(session, path, request.rights)))
            except Exception as error:
                session.rollback()
                errors.append({"name": Path(path).name, "error": str(error)})
    return {"assets": results, "errors": errors}


@app.post("/api/sources/upload")
def upload_source(file: UploadFile = File(...), rights: bool = Form(False)):
    target = STORAGE / "temp" / (uid() + Path(file.filename or "").suffix.lower())
    total = 0
    try:
        with target.open("wb") as stream:
            while chunk := file.file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD:
                    raise ValueError("Файл превышает 20 ГБ")
                stream.write(chunk)
        with Session() as session:
            asset = import_file(session, target, rights)
            asset.name = Path(file.filename or "Видео").name
            session.commit()
            return public(asset)
    finally:
        target.unlink(missing_ok=True)


@app.post("/api/sources/folder")
def add_folder(request: FolderInput):
    path = Path(request.path).resolve()
    if not path.is_dir():
        raise ValueError("Папка не найдена")
    with Session() as session:
        source = session.scalar(select(Source).where(Source.path == str(path)))
        if not source:
            source = Source(name=path.name, path=str(path))
            session.add(source)
        source.rights, source.watching = request.rights, request.watching
        session.commit()
        return dict(public(source), path=source.path)


@app.delete("/api/sources/folders/{identity}")
def unwatch_folder(identity: str):
    with Session() as session:
        source = required(session, Source, identity)
        source.watching = False
        session.commit()
    return {"stopped": True}


@app.post("/api/sources/download")
def download_source(request: DownloadInput):
    from .downloads import validate_url
    from .services import notify_workers

    if not request.rights:
        raise ValueError("Подтвердите, что у вас есть права на скачивание и монтаж материала")
    url = validate_url(request.url)
    with Session() as session:
        active = session.scalars(
            select(RenderJob).where(
                RenderJob.kind == "download", RenderJob.status.in_(["pending", "analyzing", "rendering"])
            )
        )
        if any(job.options.get("url") == url for job in active):
            raise ValueError("Это видео уже загружается; откройте очередь")
        job = RenderJob(
            kind="download",
            options={**request.model_dump(), "url": url},
            message="Ожидание скачивания YouTube / Twitch",
        )
        session.add(job)
        session.commit()
        notify_workers()
        return public(job)


@app.post("/api/sources/remote")
def import_remote(request: RemoteInput):
    from .security import public_url

    public_url(request.url)
    with Session() as session:
        update_settings(session, {"queue_paused": False})
        job = RenderJob(kind="import_remote", options=request.model_dump())
        session.add(job)
        session.commit()
        return public(job)


@app.post("/api/sources/{identity}/rights")
def confirm_rights(identity: str):
    with Session() as session:
        asset = required(session, SourceAsset, identity)
        asset.rights = True
        session.commit()
        return public(asset)


@app.get("/api/projects")
def projects():
    with Session() as session:
        return [public(row) for row in session.scalars(select(ContentProject))]


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=150)


@app.post("/api/projects")
def create_project(request: ProjectInput):
    with Session() as session:
        project = ContentProject(name=request.name)
        session.add(project)
        session.commit()
        return public(project)


@app.get("/api/jobs")
def jobs():
    with Session() as session:
        return [
            public(row)
            for row in session.scalars(select(RenderJob).order_by(RenderJob.created_at.desc()).limit(500))
        ]


@app.post("/api/jobs")
def render_jobs(request: RenderOptions):
    with Session() as session:
        return [public(job) for job in create_jobs(session, request)]


@app.post("/api/jobs/{identity}/{action}")
def job_action(identity: str, action: str):
    with Session() as session:
        job = required(session, RenderJob, identity)
        if action == "cancel" and job.status in ("pending", "analyzing", "rendering"):
            job.status, job.finished_at = "cancelled", now()
        elif action == "retry" and job.status in ("failed", "cancelled"):
            job.status, job.progress, job.error, job.finished_at = "pending", 0, None, None
        else:
            raise ValueError("Действие недоступно для текущего статуса")
        session.commit()
        return public(job)


@app.post("/api/demo")
def create_demo():
    with Session() as session:
        update_settings(session, {"queue_paused": False})
        job = RenderJob(kind="demo")
        session.add(job)
        session.commit()
        return public(job)


@app.post("/api/animation")
def create_animation():
    with Session() as session:
        update_settings(session, {"queue_paused": False})
        job = RenderJob(kind="animation")
        session.add(job)
        session.commit()
        return public(job)


@app.post("/api/control/{action}")
def control(action: str):
    with Session() as session:
        if action == "start":
            update_settings(session, {"production": "running", "queue_paused": False})
        elif action == "pause":
            update_settings(session, {"production": "paused", "queue_paused": True})
        elif action == "resume":
            update_settings(session, {"production": "running", "queue_paused": False})
        elif action == "stop":
            from .live_routes import stop_all

            stop_all(session)
            update_settings(
                session, {"production": "stopped", "queue_paused": True, "publishing_enabled": False}
            )
            session.execute(
                update(TikTokJob)
                .where(TikTokJob.status.in_(["pending", "publishing"]))
                .values(status="cancelled")
            )
            session.execute(
                update(RenderJob)
                .where(RenderJob.status.in_(["pending", "analyzing", "rendering"]))
                .values(status="cancelled", finished_at=now())
            )
            session.commit()
        elif action == "resume-queue":
            update_settings(session, {"queue_paused": False})
        else:
            raise ValueError("Неизвестная команда")
    return {"ok": True}


@app.get("/api/clips")
def clips():
    with Session() as session:
        return [
            public(row)
            for row in session.scalars(select(RenderedClip).order_by(RenderedClip.created_at.desc()))
        ]


@app.get("/api/clips/{identity}/file")
def clip_file(identity: str):
    with Session() as session:
        clip = required(session, RenderedClip, identity)
        return FileResponse(
            inside(clip.path), media_type="video/mp4", filename=f"clip-tribune-{identity[:8]}.mp4"
        )


@app.get("/api/clips/{identity}/thumbnail")
def clip_thumbnail(identity: str):
    with Session() as session:
        clip = required(session, RenderedClip, identity)
        return FileResponse(
            inside(clip.thumbnail),
            media_type="image/png" if clip.thumbnail.endswith(".png") else "image/jpeg",
        )


@app.get("/api/clips/{identity}/location")
def clip_location(identity: str):
    with Session() as session:
        clip = required(session, RenderedClip, identity)
        return {"path": str(inside(clip.path)), "thumbnail": str(inside(clip.thumbnail))}


@app.delete("/api/clips/{identity}")
def delete_clip(identity: str):
    with Session() as session:
        clip = required(session, RenderedClip, identity)
        if session.scalar(select(PublishJob.id).where(PublishJob.clip_id == identity)):
            raise ValueError("Ролик есть в истории публикации; удаление заблокировано")
        if session.scalar(select(TikTokJob.id).where(TikTokJob.clip_id == identity)):
            raise ValueError("Ролик есть в истории TikTok; удаление заблокировано")
        active = session.scalars(
            select(RenderJob).where(
                RenderJob.kind == "ad_overlay", RenderJob.status.in_(["pending", "analyzing", "rendering"])
            )
        )
        if any(job.options.get("clip_id") == identity for job in active):
            raise ValueError("Дождитесь наложения рекламы или отмените задание в очереди")
        path = inside(clip.path)
        for target in (path, path.with_suffix(".jpg"), path.with_suffix(".png"), path.with_suffix(".srt")):
            target.unlink(missing_ok=True)
        session.delete(clip)
        session.commit()
    return {"deleted": True}


@app.get("/api/trends")
def trends():
    with Session() as session:
        return [
            public(row)
            for row in session.scalars(select(TrendRecord).order_by(TrendRecord.created_at.desc()).limit(100))
        ]


@app.post("/api/trends/search")
def trends_search(request: TrendInput):
    with Session() as session:
        return [
            public(row)
            for row in youtube.search_trends(session, request.query, request.region, request.hours)
        ]


@app.get("/api/youtube/channels")
def channels():
    with Session() as session:
        return [public(row) for row in session.scalars(select(YouTubeChannel))]


@app.post("/api/youtube/connect")
def youtube_connect():
    with Session() as session:
        return {"url": youtube.oauth_start(session)}


@app.get("/api/youtube/callback", response_class=HTMLResponse)
def youtube_callback(state: str, code: str = "", error: str = ""):
    if state.startswith("tt_"):
        raise ValueError("Это не запрос авторизации YouTube")
    with Session() as session:
        if error:
            youtube.consume_state(session, state)
            return "<h1>Доступ не предоставлен</h1><p>Можно вернуться в CLIP TRIBUNE.</p>"
        youtube.oauth_callback(session, state, code)
    return '<meta charset="utf-8"><h1>Канал подключён</h1><p>Вернитесь в CLIP TRIBUNE. Это окно можно закрыть.</p>'


@app.delete("/api/youtube/channels/{identity}")
def disconnect_channel(identity: str):
    with Session() as session:
        channel = required(session, YouTubeChannel, identity)
        youtube.disconnect(session, channel)
    return {"disconnected": True}


@app.get("/api/publisher")
def publisher():
    with Session() as session:
        return {
            "jobs": [
                public(row)
                for row in session.scalars(select(PublishJob).order_by(PublishJob.created_at.desc()))
            ],
            "quota": youtube.quota_status(session),
            "enabled": settings(session)["publishing_enabled"],
        }


@app.post("/api/publisher")
def enqueue_publish(request: PublishInput):
    with Session() as session:
        return [public(row) for row in prepare_publish(session, request)]


class PublishAction(BaseModel):
    channel_id: str | None = None


class PublishSchedule(BaseModel):
    scheduled_at: float | None = None
    privacy: str | None = Field(default=None, pattern="^(private|unlisted|public)$")
    synthetic: bool | None = None
    made_for_kids: bool | None = None


@app.patch("/api/publisher/{identity}")
def schedule_publish(identity: str, request: PublishSchedule):
    with Session() as session:
        job = required(session, PublishJob, identity)
        if job.status != "pending" or (request.scheduled_at is not None and request.scheduled_at <= now()):
            raise ValueError("Можно назначить только будущее время для ожидающего задания")
        if request.privacy == "public" and not settings(session)["allow_public"]:
            raise ValueError("Публичная публикация не разрешена в настройках")
        if "scheduled_at" in request.model_fields_set:
            job.scheduled_at = request.scheduled_at
        job.options = {**job.options, **request.model_dump(exclude={"scheduled_at"}, exclude_none=True)}
        session.commit()
        return public(job)


@app.post("/api/publisher/{identity}/{action}")
def publish_action(identity: str, action: str, request: PublishAction):
    with Session() as session:
        job = required(session, PublishJob, identity)
        if action == "send":
            if job.status not in ("pending", "failed"):
                raise ValueError("Задание уже отправлено или отменено")
            if request.channel_id:
                required(session, YouTubeChannel, request.channel_id)
                job.channel_id = request.channel_id
            if not job.channel_id:
                raise ValueError("Сначала подключите и выберите канал")
            job.status = "pending"
            job.options = {**job.options, "approved": True}
            update_settings(session, {"publishing_enabled": True})
        elif action == "cancel" and job.status in ("pending", "publishing", "failed"):
            job.status, job.finished_at = "cancelled", now()
        else:
            raise ValueError("Действие недоступно")
        session.commit()
        return public(job)


@app.post("/api/publishing/stop")
def stop_publishing():
    with Session() as session:
        update_settings(session, {"publishing_enabled": False, "auto_publish": False})
    return {"stopped": True}


@app.get("/api/publisher/{identity}/processing")
def check_processing(identity: str):
    with Session() as session:
        job = required(session, PublishJob, identity)
        if not job.video_id or not job.channel_id:
            raise ValueError("Ролик ещё не загружен")
        return youtube.processing_status(
            session, required(session, YouTubeChannel, job.channel_id), job.video_id
        )
