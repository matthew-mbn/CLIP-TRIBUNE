"""Реальный FFmpeg: проверяем файлы, а не только ответы функций."""

from pathlib import Path

import pytest
from sqlalchemy import select

from backend import video
from backend.config import FFMPEG
from backend.models import ClipCandidate, RenderJob, RenderedClip
from backend.schemas import RenderOptions
from backend.services import claim_job, create_jobs, recover_jobs
from backend.worker import process_job


def test_metadata(sample_video):
    metadata = video.probe(sample_video)
    assert metadata["width"] == 640 and metadata["height"] == 360
    assert metadata["duration"] == pytest.approx(48, abs=0.1)
    assert metadata["audio"] and metadata["fps"] == 30


def test_selection_is_deterministic_and_nonoverlapping(sample_video):
    features = video.analyze(sample_video, video.probe(sample_video))
    first = video.select_candidates(features, 48, 15, 3)
    second = video.select_candidates(features, 48, 15, 3)
    assert first == second and len(first) >= 2
    for index, candidate in enumerate(first):
        assert 0 <= candidate["score"] <= 100
        assert candidate["reasons"]
        for other in first[index + 1 :]:
            assert abs(candidate["start"] - other["start"]) >= 15
    assert not video.select_candidates(features, 48, 15, 3, used=first)


def test_full_pipeline_and_publish_queue(client, session, asset):
    """Импорт → анализ → 2 MP4 → библиотека → локальная очередь публикации."""
    created = client.post(
        "/api/jobs",
        json={
            "asset_ids": [asset.id],
            "count": 2,
            "duration": 15,
            "resolution": "720",
            "framing": "blur",
            "theme": "Тестовый сигнал",
        },
    ).json()[0]
    job = claim_job(session, "test-worker")
    assert job.id == created["id"] and job.status == "analyzing"
    process_job(job.id)
    session.expire_all()
    job = session.get(RenderJob, job.id)
    assert job.status == "ready", job.error
    assert job.progress == 100 and job.metrics["render_seconds"] > 0
    clips = list(session.scalars(select(RenderedClip)))
    assert len(clips) == 2
    for clip in clips:
        metadata = video.probe(clip.path)
        assert (metadata["width"], metadata["height"]) == (720, 1280)
        assert metadata["duration"] == pytest.approx(15, abs=0.15)
        assert metadata["audio"]
        assert Path(clip.thumbnail).exists()
        assert len(clip.metadata_json["titles"]) == 3
        assert client.get(f"/api/clips/{clip.id}/file").content[:4] != b""
    assert len(client.get("/api/clips").json()) == 2
    queued = client.post("/api/publisher", json={"clip_ids": [clip.id for clip in clips]})
    assert queued.status_code == 200 and len(queued.json()) == 2
    assert all(job["status"] == "pending" for job in queued.json())
    # Повторный запрос не создаёт повторных публикаций.
    client.post("/api/publisher", json={"clip_ids": [clip.id for clip in clips]})
    assert len(client.get("/api/publisher").json()["jobs"]) == 2
    assert len(list(session.scalars(select(ClipCandidate)))) == 2


def test_silent_vertical_crop(tmp_path):
    source, target = tmp_path / "silent.mp4", tmp_path / "vertical.mp4"
    video.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30",
            "-t",
            "16",
            "-c:v",
            "libx264",
            "-threads",
            "2",
            str(source),
        ]
    )
    metadata = video.probe(source)
    assert not metadata["audio"]
    result = video.render(
        source, target, {"start": 0, "duration": 15}, {"resolution": "720", "framing": "crop"}, metadata
    )
    assert (result["width"], result["height"]) == (720, 1280)
    assert not result["audio"]


def test_overlay_and_subtitles(sample_video, tmp_path):
    from backend.providers import write_srt

    subtitle = tmp_path / "caption.srt"
    assert write_srt([{"start": 1, "end": 3, "text": "Проверка субтитров"}], 0, 15, subtitle)
    result = video.render(
        sample_video,
        tmp_path / "styled.mp4",
        {"start": 0, "duration": 15},
        {"resolution": "720", "framing": "crop", "title_overlay": True, "theme": "Clip Tribune"},
        video.probe(sample_video),
        subtitle_path=subtitle,
    )
    assert result["duration"] == pytest.approx(15, abs=0.15)


def test_ffmpeg_error_then_retry(session, asset, monkeypatch):
    job = create_jobs(session, RenderOptions(asset_ids=[asset.id], count=1, duration=15))[0]
    claim_job(session, "test")
    with monkeypatch.context() as patch:
        patch.setattr(video, "FFMPEG", "nonexistent-ffmpeg-test.exe")
        process_job(job.id)
    session.expire_all()
    job = session.get(RenderJob, job.id)
    assert job.status == "failed" and job.error
    job.status = "pending"
    session.commit()
    claim_job(session, "retry")
    process_job(job.id)
    session.expire_all()
    assert session.get(RenderJob, job.id).status == "ready"


def test_cancelled_before_render(session, asset):
    job = create_jobs(session, RenderOptions(asset_ids=[asset.id]))[0]
    job.status = "cancelled"
    session.commit()
    process_job(job.id)
    session.expire_all()
    assert session.get(RenderJob, job.id).status == "cancelled"
    assert not list(session.scalars(select(RenderedClip)))


def test_recover_queue(session):
    stale = RenderJob(status="rendering", updated_at=1)
    session.add(stale)
    session.commit()
    assert recover_jobs(session) == 1
    session.refresh(stale)
    assert stale.status == "failed" and "прерван" in stale.error


def test_claim_only_once(session):
    session.add(RenderJob())
    session.commit()
    assert claim_job(session, "first")
    assert claim_job(session, "second") is None


def test_animation(client, session):
    identity = client.post("/api/animation").json()["id"]
    claim_job(session, "test")
    process_job(identity)
    session.expire_all()
    job = session.get(RenderJob, identity)
    assert job.status == "ready", job.error
    clip = session.scalar(select(RenderedClip))
    assert video.probe(clip.path)["duration"] == pytest.approx(15, abs=0.1)
