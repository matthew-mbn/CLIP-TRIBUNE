"""Реальные пиксели и время вебки важнее проверки строки FFmpeg-фильтра."""

import base64
import io
from pathlib import Path
import pytest
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import select

from backend import video
from backend.config import FFMPEG, STORAGE
from backend.models import LiveRecording, LiveSegment, RenderJob, RenderedClip
from backend.schemas import RenderOptions, LiveInput, WebcamRegion
from backend.sources import import_file
from desktop.webcam import selection_region, composition_preview

REGION = dict(x=0.75, y=2 / 3, width=0.25, height=1 / 3)


@pytest.fixture(scope="module")
def webcam_source():
    path = STORAGE / "sources" / "webcam-test.mp4"
    video.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=640x360:r=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-vf",
            "drawbox=x=480:y=240:w=160:h=120:color=red:t=fill:enable='lt(t,8)',drawbox=x=480:y=240:w=160:h=120:color=yellow:t=fill:enable='gte(t,8)'",
            "-t",
            "16",
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-c:a",
            "aac",
            str(path),
        ]
    )
    return path


def pixels(path, second, target):
    video.run(
        [FFMPEG, "-v", "error", "-y", "-ss", str(second), "-i", str(path), "-frames:v", "1", str(target)]
    )
    with Image.open(target) as image:
        return image.convert("RGB")


def near(actual, expected):
    assert all(abs(a - b) < 35 for a, b in zip(actual, expected)), (actual, expected)


@pytest.mark.parametrize(
    "changes",
    [
        dict(x=-0.1),
        dict(width=0),
        dict(x=0.9),
        dict(y=0.9),
        dict(height=float("nan")),
        dict(width=float("inf")),
    ],
)
def test_webcam_region_rejects_invalid_coordinates(changes):
    with pytest.raises(ValidationError):
        WebcamRegion(**{**REGION, **changes})


def test_selection_and_layout_require_a_region():
    assert selection_region((1.2, 1.1), (0.75, 0.5)) == dict(x=0.75, y=0.5, width=0.25, height=0.5)
    assert selection_region((0.1, 0.1), (0.101, 0.11)) is None
    for schema in (RenderOptions, LiveInput):
        with pytest.raises(ValidationError):
            schema(url="https://www.twitch.tv/example", layout="webcam")
    assert LiveInput(url="https://www.twitch.tv/example").layout == "single"


@pytest.mark.parametrize("fit", ["crop", "fit"])
def test_webcam_half_screen_timing_audio_and_no_stretch(webcam_source, tmp_path, fit):
    output = tmp_path / "webcam.mp4"
    result = video.render(
        webcam_source,
        output,
        dict(start=7, duration=3),
        dict(layout="webcam", webcam_region=REGION, resolution="360", webcam_fit=fit, main_fit="crop"),
        video.probe(webcam_source),
    )
    assert (result["width"], result["height"]) == (360, 640)
    assert result["audio"] and result["duration"] == pytest.approx(3, abs=0.15)
    for second, color in [(0.4, (255, 0, 0)), (1.4, (255, 255, 0))]:
        image = pixels(output, second, tmp_path / "frame.png")
        near(image.getpixel((180, 160)), (0, 0, 255))
        near(image.getpixel((180, 480)), color)
        # Ровно половина экрана, а fit оставляет поля, не растягивая вебку.
        near(image.getpixel((180, 321)), (0, 0, 0) if fit == "fit" else color)
    original = pixels(webcam_source, 7.4, tmp_path / "source.png")
    preview = composition_preview(original, REGION, webcam_fit=fit)
    near(preview.getpixel((126, 112)), (0, 0, 255))
    near(preview.getpixel((126, 336)), (255, 0, 0))


def test_webcam_relative_region_survives_resolution_change(webcam_source, tmp_path):
    resized = tmp_path / "resized.mp4"
    video.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-i",
            str(webcam_source),
            "-vf",
            "scale=1280:720",
            "-t",
            "1",
            "-an",
            "-threads",
            "2",
            str(resized),
        ]
    )
    output = tmp_path / "vertical.mp4"
    result = video.render(
        resized,
        output,
        dict(start=0, duration=1),
        dict(layout="webcam", webcam_region=REGION, resolution="360"),
        video.probe(resized),
    )
    assert not result["audio"]
    near(pixels(output, 0.4, tmp_path / "frame.png").getpixel((180, 480)), (255, 0, 0))


def test_webcam_preview_rights_time_and_source_snapshot(client, session, webcam_source, asset):
    source = import_file(session, webcam_source, True)
    response = client.post("/api/webcam/frame", json=dict(asset_id=source.id, second=9))
    assert response.status_code == 200, response.text
    with Image.open(io.BytesIO(base64.b64decode(response.json()["png"]))) as image:
        assert image.size == (640, 360)
        near(image.convert("RGB").getpixel((560, 300)), (255, 255, 0))
    assert client.post("/api/webcam/frame", json=dict(asset_id=source.id, second=20)).status_code == 400
    assert (
        client.post(
            "/api/webcam/frame", json=dict(asset_id=source.id, url="https://www.twitch.tv/example")
        ).status_code
        == 422
    )
    source.rights = False
    session.commit()
    assert client.post("/api/webcam/frame", json=dict(asset_id=source.id)).status_code == 400
    source.rights = True
    session.commit()
    options = dict(asset_ids=[source.id], layout="webcam", webcam_region=REGION, count=1, duration=15)
    assert client.post("/api/jobs", json={**options, "asset_ids": [source.id, asset.id]}).status_code == 400
    job = client.post("/api/jobs", json=options).json()[0]
    assert job["options"]["webcam_region"] == REGION
    assert job["options"]["layout"] == "webcam"


def test_live_preview_uses_only_video_and_hides_network_errors(client, monkeypatch, webcam_source):
    from backend import live
    from backend.composition import media_input

    called = []
    monkeypatch.setattr(live, "resolve_stream", lambda *_: ("Live", [dict(video=False), dict(video=True)]))
    monkeypatch.setattr(
        live, "stream_inputs", lambda streams: called.append(streams) or media_input(webcam_source)
    )
    payload = dict(url="https://www.twitch.tv/example", rights=True)
    assert client.post("/api/webcam/frame", json={**payload, "rights": False}).status_code == 400
    assert client.post("/api/webcam/frame", json={**payload, "url": "http://127.0.0.1/"}).status_code == 400
    assert not called
    assert client.post("/api/webcam/frame", json={**payload, "second": 121}).status_code == 400
    assert client.post("/api/webcam/frame", json=payload).status_code == 200
    assert called == [[dict(video=True)]]
    delayed = client.post("/api/webcam/frame", json={**payload, "second": 9})
    assert delayed.status_code == 200
    with Image.open(io.BytesIO(base64.b64decode(delayed.json()["png"]))) as picture:
        near(picture.convert("RGB").getpixel((560, 300)), (255, 255, 0))

    def fail(*args, **kwargs):
        raise RuntimeError("https://example.com/?secret=signed-value")

    monkeypatch.setattr(video, "run", fail)
    response = client.post("/api/webcam/frame", json=payload)
    assert response.status_code == 400 and "signed-value" not in response.text


def test_webcam_live_job_reaches_library(session, webcam_source):
    from backend.live import queue_parts
    from backend.worker import process_job

    options = LiveInput(
        url="https://www.twitch.tv/example",
        rights=True,
        layout="webcam",
        webcam_region=REGION,
        duration=15,
        min_score=0,
    ).model_dump()
    recording = LiveRecording(
        url=options.pop("url"), platform="twitch", options=options, status="finished", clipping_enabled=True
    )
    session.add(recording)
    session.commit()
    session.add(
        LiveSegment(
            recording_id=recording.id,
            name="capture_00_000000.mkv",
            path=str(webcam_source),
            start=0,
            duration=16,
            size=webcam_source.stat().st_size,
        )
    )
    session.commit()
    queue_parts()
    job = session.scalar(select(RenderJob))
    process_job(job.id)
    session.expire_all()
    assert job.status == "ready", job.error
    clip = session.scalar(select(RenderedClip))
    assert Path(clip.path).is_file()
    assert clip.metadata_json["render_options"]["webcam_region"] == REGION
    near(pixels(clip.path, 0.4, STORAGE / "temp" / "live-webcam.png").getpixel((360, 960)), (255, 0, 0))
