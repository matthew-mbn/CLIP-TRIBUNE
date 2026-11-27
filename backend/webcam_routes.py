"""Получаем один кадр для ручного выделения вебки. Ключи соцсетей не нужны."""

import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi import APIRouter
from PIL import Image

from .config import FFMPEG, STORAGE
from .database import Session
from .models import SourceAsset
from .schemas import WebcamFrameInput
from .security import inside
from . import video

router = APIRouter(prefix="/api/webcam")


@router.post("/live-preview")
def live_preview(request: WebcamFrameInput):
    if not request.url or not request.rights:
        raise ValueError("Нужна ссылка и подтверждение права на запись эфира")
    from .live_preview import start

    return start(request.url, request.height)


@router.get("/live-preview/{identity}")
def preview_frame(identity: str):
    from .live_preview import frame

    return frame(identity)


@router.delete("/live-preview/{identity}")
def stop_preview(identity: str):
    from .live_preview import stop

    return stop(identity)


@router.post("/frame")
def frame(request: WebcamFrameInput):
    remote = bool(request.url)
    if remote:
        from .live import validate_live_url, resolve_stream, stream_inputs

        if not request.rights:
            raise ValueError("Подтвердите право на запись и использование эфира")
        if request.second > 120:
            raise ValueError("Для кадра эфира можно пропустить от 0 до 120 секунд")
        url, _ = validate_live_url(request.url)
        _, streams, _ = resolve_stream(url, request.height)
        # Для кадра достаточно видео; отдельный аудиопоток YouTube не открываем.
        inputs = stream_inputs([next(s for s in streams if s["video"])])
    else:
        from .composition import media_input

        with Session() as session:
            asset = session.get(SourceAsset, request.asset_id)
            if not asset or not asset.rights:
                raise ValueError("Выберите исходник с подтверждёнными правами")
            if request.second >= asset.metadata_json["duration"]:
                raise ValueError("Время кадра должно быть раньше конца видео")
            inputs = media_input(inside(asset.path), start=request.second)
    with TemporaryDirectory(dir=STORAGE / "temp") as temporary:
        output = Path(temporary) / "frame.png"
        try:
            video.run(
                [FFMPEG, "-v", "error", "-y"]
                + inputs
                + (["-ss", str(request.second)] if remote and request.second else [])
                + [
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    "-an",
                    "-vf",
                    "scale='min(960,iw)':-2,setsar=1",
                    "-threads",
                    "2",
                    str(output),
                ],
                timeout=40 + request.second if remote else 40,
            )
            with Image.open(output) as image:
                width, height = image.size
            return dict(png=base64.b64encode(output.read_bytes()).decode("ascii"), width=width, height=height)
        except Exception as error:
            # Ответ FFmpeg для эфира может содержать временный подписанный URL.
            raise ValueError(
                "Не удалось получить кадр. Проверьте доступность видео и повторите попытку"
            ) from error
