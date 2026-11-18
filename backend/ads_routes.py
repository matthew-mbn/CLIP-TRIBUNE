"""Настройки рекламы, предпросмотр и наложение на готовую копию ролика."""

import base64
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import ads, video
from .config import FFMPEG, STORAGE
from .database import Session, public, settings, update_settings
from .models import AdAsset, RenderJob, RenderedClip
from .schemas import AdOptions
from .services import notify_workers

router = APIRouter(prefix="/api/ads")


class ImportAd(BaseModel):
    path: str = Field(min_length=1, max_length=1024)


class PreviewAd(BaseModel):
    config: AdOptions
    clip_id: str | None = None


@router.get("")
def state():
    with Session() as session:
        return dict(
            config=AdOptions.model_validate(settings(session).get("ads", {})).model_dump(),
            assets=[public(a) for a in session.scalars(select(AdAsset).order_by(AdAsset.created_at.desc()))],
        )


@router.post("/import")
def import_asset(request: ImportAd):
    with Session() as session:
        return public(ads.import_ad(session, request.path))


@router.put("")
def save(request: AdOptions):
    with Session() as session:
        ads.snapshot(session, request.model_dump())
        update_settings(session, {"ads": request.model_dump()})
        return request.model_dump()


@router.post("/apply")
def apply(request: PreviewAd):
    with Session() as session:
        clip = session.get(RenderedClip, request.clip_id) if request.clip_id else None
        if not clip or not Path(clip.path).is_file():
            raise ValueError("Выберите готовый ролик из библиотеки")
        config = request.config.model_dump()
        config["enabled"] = True
        job = RenderJob(
            kind="ad_overlay",
            options=dict(
                clip_id=clip.id,
                framing="original",
                preset="Custom",
                layout="single",
                ad_source=ads.snapshot(session, config, clip.duration),
            ),
        )
        session.add(job)
        session.commit()
        notify_workers()
        return public(job)


@router.post("/preview")
def preview(request: PreviewAd):
    with Session() as session:
        config = request.config.model_dump()
        config.update(enabled=True, start=0)
        ad = ads.snapshot(session, config)
        clip = session.get(RenderedClip, request.clip_id) if request.clip_id else None
        if request.clip_id and not clip:
            raise ValueError("Ролик предпросмотра больше не существует")
        with TemporaryDirectory(dir=STORAGE / "temp") as folder:
            folder = Path(folder)
            if clip:
                background = folder / "background.mp4"
                video.run(
                    [
                        FFMPEG,
                        "-v",
                        "error",
                        "-y",
                        "-protocol_whitelist",
                        "file,pipe",
                        "-i",
                        clip.path,
                        "-t",
                        "1",
                        "-an",
                        "-vf",
                        "scale=360:640:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
                        "-c:v",
                        "libx264",
                        "-threads",
                        "2",
                        str(background),
                    ],
                    timeout=60,
                )
                metadata = video.probe(background)
            else:
                background = folder / "background.mp4"
                video.run(
                    [
                        FFMPEG,
                        "-v",
                        "error",
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        "color=c=0x30333d:s=360x640:r=30,drawgrid=w=60:h=60:t=1:c=white@0.12",
                        "-t",
                        "1",
                        "-c:v",
                        "libx264",
                        "-threads",
                        "2",
                        str(background),
                    ]
                )
                metadata = dict(width=360, height=640, audio=False)
            # Маленький настоящий рендер тем же кодом, что используется при экспорте.
            output = folder / "preview.mp4"
            options = dict(resolution="360", framing="original", ad_source=ad)
            video.render(background, output, dict(start=0, duration=1), options, metadata)
            image = folder / "preview.png"
            video.run(
                [FFMPEG, "-v", "error", "-y", "-ss", "0.5", "-i", str(output), "-frames:v", "1", str(image)],
                timeout=30,
            )
            return {"png": base64.b64encode(image.read_bytes()).decode("ascii")}
