"""Автор исходника не путается с темой, владельцем клипа или аккаунтом публикации."""

import json
from pathlib import Path
import pytest
from sqlalchemy import select

from backend import downloads, live, worker
from backend.models import LiveRecording, RenderedClip, RenderJob
from backend.source_identity import creator_title, recording_identity, source_identity


@pytest.mark.parametrize(
    "url,info,expected",
    [
        ("https://www.twitch.tv/t2x2", {"uploader_id": "t2x2", "title": "Другая тема"}, "TWITCH: t2x2"),
        ("https://www.twitch.tv/videos/123", {"uploader_id": "streamer"}, "TWITCH: streamer"),
        (
            "https://clips.twitch.tv/TestClip",
            {"channel": "Streamer", "uploader": "Viewer", "uploader_id": "123"},
            "TWITCH: Streamer",
        ),
        ("https://www.twitch.tv/streamer/clip/Test", {"uploader": "Viewer"}, "TWITCH: streamer"),
        ("https://clips.twitch.tv/Test", {"uploader": "Viewer"}, "TWITCH: автор не определён"),
        (
            "https://www.youtube.com/watch?v=NXtfe1zdbQE",
            {"uploader_id": "@creator", "channel": "Канал"},
            "YOUTUBE: creator",
        ),
        (
            "https://youtu.be/NXtfe1zdbQE",
            {"channel": "Мой канал", "channel_id": "UC123"},
            "YOUTUBE: Мой канал",
        ),
        ("https://www.youtube.com/@%D0%90%D0%B2%D1%82%D0%BE%D1%80/live", {}, "YOUTUBE: Автор"),
        (
            "https://www.youtube.com/watch?v=NXtfe1zdbQE",
            {"channel_id": "UC123", "title": "Тема видео"},
            "YOUTUBE: автор не определён",
        ),
        ("https://example.org/local.mp4", {"channel": "Creator"}, ""),
    ],
)
def test_titles_use_source_author(url, info, expected):
    assert creator_title(source_identity(info, url)) == expected


def test_title_is_single_line_and_fits_youtube_limit():
    title = creator_title(dict(source_platform="youtube", source_creator="@Имя\r\nканала\x00 " + "я" * 120))
    assert title.startswith("YOUTUBE: Имя канала ")
    assert len(title) == 100 and "\n" not in title and "\x00" not in title


def fake_downloader(monkeypatch, info):
    import yt_dlp

    class FakeDownloader:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, *args, **kwargs):
            return info

        def process_info(self, value):
            Path(self.options["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(b"test")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeDownloader)


def test_resolve_and_persist_live_creator(session, monkeypatch):
    url = "https://www.youtube.com/watch?v=NXtfe1zdbQE"
    fake_downloader(
        monkeypatch,
        dict(
            title="Эфир о другом",
            uploader_id="@TestCreator",
            is_live=True,
            url="https://media.example/temporary?token=secret",
            vcodec="h264",
            acodec="aac",
        ),
    )
    title, streams, identity = live.resolve_stream(url, 720)
    record = LiveRecording(url=url, platform="youtube")
    session.add(record)
    session.commit()
    live.set_state(record.id, title=title, creator_name=identity["source_creator"])
    session.refresh(record)
    assert record.creator_name == "TestCreator" and streams[0]["video"]
    assert creator_title(recording_identity(record)) == "YOUTUBE: TestCreator"
    assert "secret" not in json.dumps(identity)


def test_download_child_returns_streamer_not_clip_creator(monkeypatch, tmp_path):
    fake_downloader(monkeypatch, dict(title="Тема клипа", channel="Streamer", uploader="Viewer"))
    downloads._download("https://clips.twitch.tv/Test", 720, str(tmp_path))
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert creator_title(result["source_identity"]) == "TWITCH: Streamer"
    assert result["title"] == "Тема клипа"


@pytest.mark.parametrize("platform", ["twitch", "youtube"])
def test_saved_clip_uses_author_even_with_ai_titles(session, asset, sample_video, monkeypatch, platform):
    # Проходим реальное сохранение в библиотеку; только видео и AI заменены заглушками.
    asset.metadata_json = {**asset.metadata_json, "source_platform": platform, "source_creator": "Creator"}
    job = RenderJob(kind="render", asset_id=asset.id, options={})
    session.add(job)
    session.commit()
    monkeypatch.setattr(
        worker, "content_metadata", lambda *a: dict(titles=["AI придумал заголовок"], provider="llm")
    )
    monkeypatch.setattr(worker.video, "thumbnail", lambda *a: None)
    worker.save_clip(
        session,
        job,
        asset,
        None,
        sample_video,
        dict(start=30, duration=15, score=10, reasons=[]),
        "Произвольная тема",
    )
    clip = session.scalar(select(RenderedClip))
    assert clip.title == platform.upper() + ": Creator"
    assert clip.metadata_json["titles"] == [clip.title]
    assert clip.metadata_json["source_creator"] == "Creator"
