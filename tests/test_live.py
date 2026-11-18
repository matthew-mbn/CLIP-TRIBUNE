"""Проверяем ограничения записи, порядок окон и настоящий FFmpeg-монтаж."""

from pathlib import Path
import pytest
from sqlalchemy import select

from backend.config import FFMPEG, STORAGE
from backend.models import LiveRecording, LiveSegment, RenderJob, RenderedClip, SourceAsset
from backend.schemas import LiveInput
from backend import live, video


@pytest.mark.parametrize(
    "url,platform",
    [
        ("https://www.youtube.com/watch?v=NXtfe1zdbQE", "youtube"),
        ("https://youtu.be/NXtfe1zdbQE?t=8", "youtube"),
        ("https://www.youtube.com/@example/live", "youtube"),
        ("https://www.twitch.tv/example", "twitch"),
    ],
)
def test_live_urls(url, platform):
    assert live.validate_live_url(url)[1] == platform


@pytest.mark.parametrize(
    "url",
    [
        "http://www.twitch.tv/example",
        "https://127.0.0.1/test",
        "file:///test.m3u8",
        "https://youtube.com.attacker.test/watch?v=NXtfe1zdbQE",
        "https://user:pass@twitch.tv/example",
        "https://www.twitch.tv/videos/1234",
        "https://www.twitch.tv/directory",
        "https://clips.twitch.tv/Test",
    ],
)
def test_live_rejects_other_inputs(url):
    with pytest.raises(ValueError):
        live.validate_live_url(url)


def test_live_rights_slot_and_stop(client):
    payload = dict(url="https://www.twitch.tv/example")
    assert client.post("/api/live", json=payload).status_code == 400
    payload["rights"] = True
    first = client.post("/api/live", json=payload)
    assert first.status_code == 200
    assert client.post("/api/live", json=payload).status_code == 400
    identity = first.json()["id"]
    assert client.post(f"/api/live/{identity}/export").status_code == 400
    stopped = client.post(f"/api/live/{identity}/stop").json()
    assert stopped["status"] == "stopped" and stopped["active_slot"] is None
    assert client.post("/api/live", json=payload).status_code == 200


def make_recording(session):
    options = LiveInput(
        url="https://www.twitch.tv/example", rights=True, duration=15, min_score=0, resolution="720"
    ).model_dump()
    options.update(preset="Gaming Viral", theme="Проверка эфира", ad_source=None)
    recording = LiveRecording(
        url=options["url"], platform="twitch", options=options, status="finished", clipping_enabled=True
    )
    session.add(recording)
    session.commit()
    return recording


def test_live_queue_is_sequential_and_stop_disables_unqueued(session, client):
    recording = make_recording(session)
    for i in range(3):
        session.add(
            LiveSegment(
                recording_id=recording.id,
                name=f"part{i}.mkv",
                path="unused",
                start=i * 60,
                duration=60,
                size=1000,
            )
        )
    session.commit()
    live.queue_parts()
    jobs = session.scalars(select(RenderJob)).all()
    assert len(jobs) == 1
    live.queue_parts()
    assert len(session.scalars(select(RenderJob)).all()) == 1
    jobs[0].status = "ready"
    session.commit()
    live.queue_parts()
    assert len(session.scalars(select(RenderJob)).all()) == 2
    client.post("/api/control/stop")
    live.queue_parts()
    assert len(session.scalars(select(RenderJob)).all()) == 2


def test_live_segments_clips_and_export(session, sample_video):
    from backend.worker import process_job
    from backend.live_routes import export

    recording = make_recording(session)
    folder = STORAGE / "live" / recording.id
    folder.mkdir(parents=True)
    video.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-i",
            str(sample_video),
            "-c",
            "copy",
            "-f",
            "segment",
            "-segment_time",
            "24",
            "-reset_timestamps",
            "1",
            "-segment_list_type",
            "csv",
            "-segment_list",
            str(folder / "parts_00.csv"),
            str(folder / "capture_00_%06d.mkv"),
        ]
    )
    paths = live.closed_paths(folder, 0)
    assert len(paths) >= 2
    live.register_parts(recording.id, paths)
    live.register_parts(recording.id, paths)
    assert len(session.scalars(select(LiveSegment)).all()) == len(paths)
    live.queue_parts()
    first = session.scalar(select(RenderJob))
    process_job(first.id)
    session.expire_all()
    assert session.get(RenderJob, first.id).status == "ready"
    first_clips = session.scalars(select(RenderedClip)).all()
    assert len(first_clips) == 1
    assert video.probe(first_clips[0].path)["audio"]
    # Повтор после сбоя не создаёт вторую копию уже сохранённого результата.
    process_job(first.id)
    assert len(session.scalars(select(RenderedClip)).all()) == 1
    live.queue_parts()
    second = session.scalar(select(RenderJob).where(RenderJob.id != first.id))
    process_job(second.id)
    session.expire_all()
    assert session.get(RenderJob, second.id).status == "ready"
    clips = session.scalars(select(RenderedClip)).all()
    assert len(clips) == 2
    intervals = sorted((c.metadata_json["recording_start"], c.duration) for c in clips)
    assert intervals[1][0] >= intervals[0][0] + intervals[0][1] - 0.1
    job = export(recording.id)
    process_job(job["id"])
    session.expire_all()
    assert session.get(RenderJob, job["id"]).status == "ready"
    asset = session.scalar(select(SourceAsset))
    assert asset and Path(asset.path).is_file()
    assert abs(video.probe(asset.path)["duration"] - video.probe(sample_video)["duration"]) < 1


def test_recording_proxy_applies_only_to_input(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "getproxies", lambda: {"https": "http://127.0.0.1:9999"})
    command = live.capture_command(
        [dict(url="https://media.example/test.m3u8", headers={}, video=True, audio=True)], tmp_path, 0, 120
    )
    assert command.index("-http_proxy") < command.index("-i")
    assert "httpproxy" in command[command.index("-protocol_whitelist") + 1]
    assert command[-1].endswith("capture_00_%06d.mkv")


def test_export_normalizes_resolution_and_missing_audio(session):
    from backend.worker import process_job
    from backend.live_routes import export

    recording = make_recording(session)
    recording.clipping_enabled = False
    session.commit()
    folder = STORAGE / "live" / recording.id
    folder.mkdir(parents=True)
    original = folder / "original.mp4"
    video.make_test_video(original, 2)
    first = folder / "capture_00_000000.mkv"
    second = folder / "capture_00_000001.mkv"
    video.run([FFMPEG, "-v", "error", "-y", "-i", str(original), "-c", "copy", str(first)])
    video.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-i",
            str(original),
            "-vf",
            "scale=320:180",
            "-an",
            "-c:v",
            "libx264",
            "-threads",
            "2",
            str(second),
        ]
    )
    live.register_parts(recording.id, [first, second])
    job = export(recording.id)
    process_job(job["id"])
    session.expire_all()
    assert session.get(RenderJob, job["id"]).status == "ready"
    asset = session.scalar(select(SourceAsset))
    output = video.probe(asset.path)
    assert output["audio"] and output["width"] == 640 and output["height"] == 360
    assert abs(output["duration"] - 4) < 0.2
    assert first.exists() and second.exists()
