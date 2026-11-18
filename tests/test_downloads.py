"""Границы URL, отказ от эфиров, очередь и импорт без обращений к соцсетям."""

import pytest
from sqlalchemy import select

from backend import downloads
from backend.models import RenderJob, SourceAsset
from backend.services import claim_job
from backend.video import Cancelled
from backend.worker import process_job


@pytest.mark.parametrize(
    "url",
    [
        "https://youtu.be/BaW_jenozKc?si=test",
        "https://www.youtube.com/watch?v=BaW_jenozKc&list=ignored",
        "https://youtube.com/shorts/BaW_jenozKc",
        "https://www.twitch.tv/videos/123456789",
        "https://www.twitch.tv/test/clip/SomeClip",
        "https://clips.twitch.tv/SomeClip",
    ],
)
def test_supported_links(url):
    assert "?si=" not in downloads.validate_url(url)
    assert "list=" not in downloads.validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.youtube.com/watch?v=BaW_jenozKc",
        "https://youtube.com.evil.test/watch?v=BaW_jenozKc",
        "https://youtube.com@127.0.0.1/watch?v=BaW_jenozKc",
        "https://127.0.0.1/video.mp4",
        "https://youtube.com/playlist?list=anything",
        "https://www.twitch.tv/channel",
        "https://www.youtube.com:8443/watch?v=BaW_jenozKc",
        "file:///C:/private.mp4",
    ],
)
def test_unsupported_links(url):
    with pytest.raises(ValueError):
        downloads.validate_url(url)


def test_download_requires_rights_and_deduplicates(client):
    body = dict(url="https://youtu.be/BaW_jenozKc", height=720)
    assert client.post("/api/sources/download", json=body).status_code == 400
    body["rights"] = True
    assert client.post("/api/sources/download", json=body).status_code == 200
    assert client.post("/api/sources/download", json=body).status_code == 400


def test_reject_live_private_and_long():
    assert downloads.reject_media({"is_live": True})
    assert downloads.reject_media({"live_status": "is_upcoming"})
    assert downloads.reject_media({"duration": 36000})
    assert downloads.reject_media({"availability": "private"})
    assert downloads.reject_media({"duration": 30, "live_status": "was_live"}) is None


def test_download_job_imports_and_handles_cancel(client, session, sample_video, monkeypatch):
    def fake_download(url, height, folder, cancelled, progress):
        progress(dict(progress=80, message="Тестовая передача файла"))
        return (
            sample_video,
            "Тестовый источник",
            dict(source_platform="youtube", source_creator="TestCreator", source_url=url),
        )

    monkeypatch.setattr(downloads, "download", fake_download)
    body = dict(url="https://youtu.be/BaW_jenozKc", rights=True)
    identity = client.post("/api/sources/download", json=body).json()["id"]
    claim_job(session, "test")
    process_job(identity)
    session.expire_all()
    assert session.get(RenderJob, identity).status == "ready"
    asset = session.scalar(select(SourceAsset))
    assert asset.name == "Тестовый источник.mp4"
    assert asset.metadata_json["source_creator"] == "TestCreator"
    assert asset.metadata_json["source_platform"] == "youtube"
    identity = client.post("/api/sources/download", json=body).json()["id"]
    monkeypatch.setattr(downloads, "download", lambda *args: (_ for _ in ()).throw(Cancelled()))
    claim_job(session, "test")
    process_job(identity)
    session.expire_all()
    assert session.get(RenderJob, identity).status == "cancelled"
