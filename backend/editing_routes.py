"""Локальные команды экспорта и монтажа."""

from pathlib import Path
from fastapi import APIRouter
from pydantic import BaseModel, Field
from .database import Session, settings, update_settings
from .models import RenderedClip
from .exports import copy_video
from .captions import CaptionEdit
from .database import public
from .models import RenderJob
from sqlalchemy import select

router = APIRouter(prefix="/api/editing")


class ExportFolder(BaseModel):
    folder: str = Field(max_length=1024)


class ExportClips(ExportFolder):
    clip_ids: list[str] = Field(min_length=1, max_length=1000)


@router.get("/folder")
def folder():
    with Session() as session:
        return {"folder": settings(session)["output_folder"]}


@router.put("/folder")
def set_folder(request: ExportFolder):
    path = str(Path(request.folder).expanduser().resolve()) if request.folder else ""
    if path:
        Path(path).mkdir(parents=True, exist_ok=True)
    with Session() as session:
        update_settings(session, {"output_folder": path})
    return {"folder": path}


@router.post("/export")
def export(request: ExportClips):
    if not request.folder.strip():
        raise ValueError("Выберите папку для экспорта")
    with Session() as session:
        clips = [session.get(RenderedClip, identity) for identity in dict.fromkeys(request.clip_ids)]
        if any(not clip or not Path(clip.path).is_file() for clip in clips):
            raise ValueError("Один из выбранных роликов больше не найден")
        return {"paths": [copy_video(c.path, request.folder, c.title, c.id) for c in clips]}


@router.get("/captions/{identity}")
def get_captions(identity: str):
    from . import captions, speech

    with Session() as session:
        clip = session.get(RenderedClip, identity)
        if not clip:
            raise ValueError("Ролик не найден")
        return dict(
            **captions.load(clip).model_dump(),
            duration=clip.duration,
            speech_ready=speech.ready(),
            legacy_burned=Path(clip.path).with_suffix(".srt").exists()
            and not Path(clip.path).with_suffix(".clean.mp4").exists(),
        )


def enqueue(kind, identity=None, data=None):
    with Session() as session:
        clip = session.get(RenderedClip, identity) if identity else None
        if identity and not clip:
            raise ValueError("Ролик не найден")
        for job in session.scalars(
            select(RenderJob).where(RenderJob.status.in_(["pending", "analyzing", "rendering"]))
        ):
            if job.kind == kind and job.options.get("clip_id") == identity:
                raise ValueError("Это задание уже в очереди")
        if data and any(c.end > clip.duration + 0.05 for c in data.cues):
            raise ValueError("Фраза выходит за конец ролика")
        job = RenderJob(
            kind=kind, options=dict(clip_id=identity, captions=data.model_dump() if data else None)
        )
        session.add(job)
        session.commit()
        # Явный запуск редактора снимает паузу очереди, как запуск монтажа.
        update_settings(session, {"queue_paused": False})
        return public(job)


@router.post("/speech/install")
def install_speech():
    return enqueue("speech_setup")


@router.post("/captions/{identity}/recognize")
def recognize(identity: str):
    return enqueue("caption_transcribe", identity)


@router.post("/captions/{identity}/render")
def render_captions(identity: str, request: CaptionEdit):
    return enqueue("caption_render", identity, request)


class CaptionPreview(CaptionEdit):
    second: float = Field(default=0, ge=0, allow_inf_nan=False)


@router.post("/captions/{identity}/preview")
def preview_captions(identity: str, request: CaptionPreview):
    import base64
    from tempfile import TemporaryDirectory
    from .config import STORAGE, FFMPEG
    from . import captions, video

    with Session() as session:
        clip = session.get(RenderedClip, identity)
        if not clip or request.second >= clip.duration:
            raise ValueError("Выберите время внутри ролика")
        source = captions.clean_source(clip)
        with TemporaryDirectory(dir=STORAGE / "temp") as folder:
            ass, png = Path(folder) / "preview.ass", Path(folder) / "preview.png"
            captions.write_ass(ass, request)
            escaped = str(ass).replace("\\", "/").replace(":", r"\:")
            video.run(
                [
                    FFMPEG,
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-vf",
                    f"subtitles=filename='{escaped}',scale=360:-2",
                    "-ss",
                    str(request.second),
                    "-frames:v",
                    "1",
                    str(png),
                ],
                timeout=90,
            )
            return {"png": base64.b64encode(png.read_bytes()).decode("ascii")}
