"""Проверяем пиксели, время показа, повтор и звук настоящих MP4, а не строки команд."""

import base64
import io
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from backend import ads, video
from backend.config import FFMPEG
from backend.database import update_settings
from backend.models import RenderJob, RenderedClip
from backend.schemas import AdOptions, RenderOptions
from backend.security import file_hash
from backend.services import claim_job, create_jobs
from backend.sources import import_file
from backend.worker import process_job


def make_color(path, color, duration=4, extra="", frequency=None):
    command = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=180x320:r=30" + extra]
    if frequency:
        command += ["-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=44100"]
    command += ["-t", str(duration), "-c:v", "libx264", "-threads", "2", "-pix_fmt", "yuv420p"]
    if frequency:
        command += ["-c:a", "aac"]
    video.run(command + [str(path)])
    return path


@pytest.fixture
def composition_media(tmp_path):
    base = make_color(tmp_path / "base.mp4", "blue", frequency=440)
    bottom = make_color(
        tmp_path / "bottom.mp4",
        "yellow",
        duration=3,
        extra=",drawbox=x=0:y=0:w=iw:h=ih:color=cyan:t=fill:enable='gte(t,1)',drawbox=x=0:y=0:w=iw:h=ih:color=magenta:t=fill:enable='gte(t,2)'",
        frequency=880,
    )
    creative = make_color(
        tmp_path / "advert.mp4",
        "0x00ff00",
        duration=1,
        extra=",drawbox=x=45:y=80:w=90:h=160:color=red:t=fill",
        frequency=1200,
    )
    return base, bottom, creative


def frame(path, second, tmp_path):
    target = tmp_path / f"frame-{second}.png"
    video.run(
        [FFMPEG, "-v", "error", "-y", "-ss", str(second), "-i", str(path), "-frames:v", "1", str(target)]
    )
    with Image.open(target) as image:
        return image.convert("RGB")


def near(color, expected):
    assert all(abs(actual - target) < 35 for actual, target in zip(color, expected)), color


@pytest.mark.parametrize("mode", ["once", "banner"])
def test_ad_chromakey_timing_and_loop(session, composition_media, tmp_path, mode):
    base, _, creative = composition_media
    asset = ads.import_ad(session, creative)
    config = AdOptions(
        enabled=True, asset_id=asset.id, mode=mode, start=1, position="center", width_percent=50
    )
    output = tmp_path / "result.mp4"
    video.render(
        base,
        output,
        dict(start=0, duration=4),
        dict(resolution="360", framing="crop", ad_source=ads.snapshot(session, config.model_dump())),
        video.probe(base),
    )
    assert video.probe(output)["duration"] == pytest.approx(4, abs=0.15)
    for time in (0.4, 1.4, 2.4, 3.4):
        image = frame(output, time, tmp_path)
        showing = mode == "banner" or 1 <= time < 2
        near(image.getpixel((180, 320)), (255, 0, 0) if showing else (0, 0, 255))
        # Эта точка внутри зелёной части вставки: здесь должен быть виден синий фон.
        near(image.getpixel((105, 180)), (0, 0, 255))


@pytest.mark.parametrize("sound", ["top", "bottom", "mix", "mute"])
def test_split_offset_loop_and_audio(session, composition_media, tmp_path, sound):
    base, bottom, creative = composition_media
    ad = ads.import_ad(session, creative)
    options = dict(
        resolution="360",
        layout="split",
        secondary_start=1,
        secondary_loop=True,
        split_fit="crop",
        split_audio=sound,
        split_source=dict(path=str(bottom), metadata=video.probe(bottom)),
        ad_source=ads.snapshot(
            session,
            AdOptions(
                enabled=True, asset_id=ad.id, mode="banner", position="center", width_percent=20
            ).model_dump(),
        ),
    )
    output = tmp_path / "split.mp4"
    result = video.render(base, output, dict(start=0, duration=4), options, video.probe(base))
    assert (result["width"], result["height"]) == (360, 640)
    assert result["duration"] == pytest.approx(4, abs=0.15)
    assert result["audio"] == (sound != "mute")
    # Повтор начинается с указанной секунды, а не с отброшенного начала файла.
    for second, expected in [(0.4, (0, 255, 255)), (1.4, (255, 0, 255)), (2.4, (0, 255, 255))]:
        image = frame(output, second, tmp_path)
        near(image.getpixel((180, 80)), (0, 0, 255))
        near(image.getpixel((180, 560)), expected)
    if sound != "mute":
        import array
        import math

        pcm = tmp_path / "audio.pcm"
        video.run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-ss",
                "0.3",
                "-i",
                str(output),
                "-t",
                "0.5",
                "-vn",
                "-ar",
                "8000",
                "-ac",
                "1",
                "-f",
                "s16le",
                str(pcm),
            ]
        )
        samples = array.array("h", pcm.read_bytes())

        def energy(frequency):
            real = sum(
                value * math.cos(2 * math.pi * frequency * i / 8000) for i, value in enumerate(samples)
            )
            imaginary = sum(
                value * math.sin(2 * math.pi * frequency * i / 8000) for i, value in enumerate(samples)
            )
            return math.hypot(real, imaginary) / len(samples)

        top, lower, advert = [energy(f) for f in (440, 880, 1200)]
        if sound == "top":
            assert top > lower * 10
        elif sound == "bottom":
            assert lower > top * 10
        else:
            assert min(top, lower) > 200
        assert advert < max(top, lower) / 10  # Реклама всегда без собственной аудиодорожки.


def test_settings_snapshot_and_split_validation(client, session, asset, composition_media):
    _, bottom, creative = composition_media
    secondary = import_file(session, bottom, True)
    ad = ads.import_ad(session, creative)
    config = AdOptions(enabled=True, asset_id=ad.id, mode="banner").model_dump()
    assert client.put("/api/ads", json=config).status_code == 200
    options = RenderOptions(
        asset_ids=[asset.id], layout="split", secondary_asset_id=secondary.id, duration=15, count=1
    )
    with pytest.raises(ValueError, match="короткий"):
        create_jobs(session, options.model_copy(update={"secondary_loop": False}))
    with pytest.raises(ValueError, match="конца"):
        create_jobs(session, options.model_copy(update={"secondary_start": 10}))
    secondary.rights = False
    session.commit()
    with pytest.raises(ValueError, match="правами"):
        create_jobs(session, options)
    secondary.rights = True
    session.commit()
    job = create_jobs(session, options)[0]
    assert client.put("/api/ads", json={"enabled": False}).status_code == 200
    session.refresh(job)
    assert job.options["ad_source"]["asset_id"] == ad.id
    assert job.options["split_source"]["id"] == secondary.id
    assert "path" not in client.get("/api/ads").json()["assets"][0]


def test_image_preview_and_existing_clip_copy(client, session, composition_media, tmp_path):
    base, _, _ = composition_media
    image_path = tmp_path / "banner.png"
    image = Image.new("RGB", (120, 80), "#00ff00")
    image.paste((255, 0, 0), (20, 20, 100, 60))
    image.save(image_path)
    imported = client.post("/api/ads/import", json={"path": str(image_path)}).json()
    config = AdOptions(asset_id=imported["id"], mode="banner", position="center").model_dump()
    response = client.post("/api/ads/preview", json={"config": config})
    assert response.status_code == 200, response.text
    with Image.open(io.BytesIO(base64.b64decode(response.json()["png"]))) as preview:
        assert preview.size == (360, 640)
        near(preview.convert("RGB").getpixel((180, 320)), (255, 0, 0))
    source_job = RenderJob(status="ready")
    session.add(source_job)
    session.commit()
    clip = RenderedClip(
        job_id=source_job.id,
        title="Исходный ролик",
        path=str(base),
        thumbnail="",
        duration=4,
        size=base.stat().st_size,
        score=20,
        sha256=file_hash(base),
        metadata_json=dict(titles=["Исходный ролик"], description="Описание", hashtags=[]),
    )
    session.add(clip)
    session.commit()
    digest = file_hash(base)
    queued = client.post("/api/ads/apply", json={"config": config, "clip_id": clip.id})
    assert queued.status_code == 200, queued.text
    assert client.delete(f"/api/clips/{clip.id}").status_code == 400
    claim_job(session, "test")
    process_job(queued.json()["id"])
    session.expire_all()
    job = session.get(RenderJob, queued.json()["id"])
    assert job.status == "ready", job.error
    clips = list(session.scalars(select(RenderedClip)))
    assert len(clips) == 2 and file_hash(base) == digest
    copy = next(item for item in clips if item.id != clip.id)
    assert video.probe(copy.path)["width"] == 180
    assert copy.title.endswith("· реклама") and Path(copy.path).is_file()


def test_ad_time_outside_clip_is_rejected(session, asset, composition_media):
    ad = ads.import_ad(session, composition_media[2])
    update_settings(session, {"ads": AdOptions(enabled=True, asset_id=ad.id, start=20).model_dump()})
    with pytest.raises(ValueError, match="после конца"):
        create_jobs(session, RenderOptions(asset_ids=[asset.id], duration=15))
    job = create_jobs(session, RenderOptions(asset_ids=[asset.id], duration=15, use_ads=False))[0]
    assert job.options["ad_source"] is None
