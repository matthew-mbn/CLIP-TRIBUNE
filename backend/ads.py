"""Импорт рекламы и снимок настроек для очереди. Оригиналы не изменяются."""

import shutil
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy import select

from .config import STORAGE, VIDEO_EXTENSIONS
from .database import settings
from .models import AdAsset, uid
from .schemas import AdOptions
from .security import file_hash
from .video import probe


def import_ad(session, source):
    source = Path(source).resolve()
    images = {".png", ".jpg", ".jpeg", ".webp"}
    suffix = source.suffix.lower()
    if not source.is_file() or suffix not in images | set(VIDEO_EXTENSIONS):
        raise ValueError("Выберите MP4, MOV, MKV, WEBM, PNG, JPG или WEBP")
    if source.stat().st_size > 500 * 1024**2:
        raise ValueError("Рекламная вставка должна быть меньше 500 МБ")
    digest = file_hash(source)
    existing = session.scalar(select(AdAsset).where(AdAsset.sha256 == digest))
    if existing:
        return existing
    folder = STORAGE / "ads"
    folder.mkdir(exist_ok=True)
    kind = "image" if suffix in images else "video"
    target = folder / (uid() + (".png" if kind == "image" else suffix))
    try:
        if kind == "image":
            with Image.open(source) as image:
                if image.width * image.height > 25_000_000:
                    raise ValueError("Изображение должно быть не больше 25 мегапикселей")
                image = ImageOps.exif_transpose(image).convert("RGBA")
                metadata = dict(width=image.width, height=image.height, duration=5, audio=False)
                image.save(target)
        else:
            metadata = probe(source)
            if metadata["duration"] > 600:
                raise ValueError("Вставка должна быть не длиннее 10 минут")
            shutil.copyfile(source, target)
        asset = AdAsset(name=source.name, path=str(target), kind=kind, sha256=digest, metadata_json=metadata)
        session.add(asset)
        session.commit()
        return asset
    except Exception:
        target.unlink(missing_ok=True)
        session.rollback()
        raise


def snapshot(session, config=None, duration=None):
    """Путь берём только из импортированного материала, не из HTTP-параметров."""
    options = AdOptions.model_validate(config if config is not None else settings(session).get("ads", {}))
    if not options.enabled:
        return None
    asset = session.get(AdAsset, options.asset_id)
    if not asset or not Path(asset.path).is_file():
        raise ValueError("В разделе «Реклама» выберите существующую вставку")
    if options.mode == "once" and duration is not None and options.start >= duration:
        raise ValueError("Реклама начинается после конца ролика. Уменьшите время начала вставки")
    return {
        **options.model_dump(),
        "path": asset.path,
        "kind": asset.kind,
        "name": asset.name,
        "metadata": dict(asset.metadata_json),
    }
