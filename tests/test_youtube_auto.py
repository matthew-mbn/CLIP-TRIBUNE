"""Автопубликация в одну или обе платформы, без реальных внешних запросов."""

import json
import httpx
import pytest
from sqlalchemy import select
from backend import youtube, youtube_auto, tiktok
from backend.database import Session, settings, update_settings
from backend.models import LiveRecording, PublishJob, TikTokJob, YouTubeChannel, now
from backend.security import encrypt
from test_tiktok import account as account, clip as clip, CREATOR, ok
from test_tiktok_auto import another_clip


@pytest.fixture
def channel(session):
    value = YouTubeChannel(
        youtube_id="yt-test",
        name="Test channel",
        tokens=encrypt(dict(access_token="yt-test-token", refresh_token="test", expires_at=now() + 3600)),
    )
    session.add(value)
    session.commit()
    return value


@pytest.fixture
def remote(monkeypatch):
    bodies = []

    def handler(request):
        if request.method == "POST":
            bodies.append(json.loads(request.content))
            return httpx.Response(200, headers={"Location": "https://www.googleapis.com/upload/session/test"})
        if request.headers["Content-Range"].startswith("bytes */"):
            return httpx.Response(308)
        return httpx.Response(200, json={"id": "youtube-video"})

    original = httpx.Client
    monkeypatch.setattr(
        youtube.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(tiktok, "creator_info", lambda *a: CREATOR)
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: ok(
            {"publish_id": "tt-video", "upload_url": "https://open-upload.tiktokapis.com/video/"}
        ),
    )
    monkeypatch.setattr(httpx, "put", lambda *a, **k: httpx.Response(201))
    return bodies


def start(client, session, clip, channel, account, target="both", **youtube_options):
    payload = dict(
        url="https://www.twitch.tv/example",
        rights=True,
        youtube_auto=dict(
            enabled=target in ("youtube", "both"),
            channel_id=channel.id,
            consent=True,
            privacy="unlisted",
            **youtube_options,
        ),
        tiktok_auto=dict(
            enabled=target in ("tiktok", "both"),
            account_id=account.id,
            consent=True,
            privacy_level="SELF_ONLY",
        ),
    )
    result = client.post("/api/live", json=payload)
    assert result.status_code == 200, result.text
    record = session.get(LiveRecording, result.json()["id"])
    clip.metadata_json = {"live_id": record.id}
    session.commit()
    return record


@pytest.mark.parametrize("target", ["youtube", "tiktok", "both"])
def test_only_selected_platforms_receive_clip(client, session, clip, channel, account, remote, target):
    record = start(
        client, session, clip, channel, account, target, synthetic=True, paid_product_placement=True
    )
    youtube_auto.tick()
    tiktok.tick()
    yt = session.scalars(select(PublishJob)).all()
    tt = session.scalars(select(TikTokJob)).all()
    assert len(yt) == (target in ("youtube", "both"))
    assert len(tt) == (target in ("tiktok", "both"))
    if yt:
        assert yt[0].status == "published" and yt[0].video_id == "youtube-video"
        assert remote[0]["status"]["privacyStatus"] == "unlisted"
        assert remote[0]["status"]["containsSyntheticMedia"] is True
        assert remote[0]["paidProductPlacementDetails"]["hasPaidProductPlacement"] is True
    if tt:
        assert tt[0].status == "processing"
    assert not settings(session)["publishing_enabled"]  # Ручная очередь не включилась.
    assert record.options["youtube_auto"]["channel_id"] == channel.id


def test_youtube_failure_does_not_disable_tiktok(
    client, session, clip, channel, account, remote, monkeypatch
):
    record = start(client, session, clip, channel, account)

    def fail(*a, **k):
        raise httpx.ReadTimeout("https://secret-url/?token=hidden")

    monkeypatch.setattr(youtube, "upload", fail)
    youtube_auto.tick()
    tiktok.tick()
    session.refresh(record)
    assert not record.auto_youtube_enabled and record.auto_tiktok_enabled
    assert "hidden" not in record.youtube_auto_state["error"]
    assert session.scalar(select(TikTokJob)).status == "processing"


@pytest.mark.parametrize("action", ["youtube/stop", "stop", "global", "publishing"])
def test_stop_prevents_youtube_transfer(client, session, clip, channel, account, remote, action):
    record = start(client, session, clip, channel, account)
    youtube_auto.queue_once()
    path = {"global": "/api/control/stop", "publishing": "/api/publishing/stop"}.get(
        action, f"/api/live/{record.id}/{action}"
    )
    assert client.post(path).status_code == 200
    youtube_auto.tick()
    session.refresh(record)
    assert not record.auto_youtube_enabled and not remote
    assert session.scalar(select(PublishJob)).status == "cancelled"
    assert record.auto_tiktok_enabled == (action in ("youtube/stop", "publishing"))


def test_manual_queue_not_sent_and_series_respects_interval_cap(
    client, session, clip, channel, account, remote
):
    record = start(client, session, clip, channel, account, "youtube", max_posts=2)
    other = another_clip(session, clip, "unrelated")
    manual = PublishJob(clip_id=other.id, channel_id=channel.id, options={"approved": True})
    session.add(manual)
    session.commit()
    youtube_auto.tick()
    second = another_clip(session, clip, record.id)
    youtube_auto.tick()
    assert len(remote) == 1
    session.refresh(record)
    youtube_auto.set_state(record, next_at=0)
    session.commit()
    youtube_auto.tick()
    youtube_auto.tick()
    session.refresh(record)
    session.refresh(manual)
    assert len(remote) == 2 and not record.auto_youtube_enabled
    assert manual.status == "pending"
    assert session.scalar(select(PublishJob).where(PublishJob.clip_id == second.id)).status == "published"


def test_stop_during_setup_does_not_enqueue(client, session, clip, channel, account, remote, monkeypatch):
    record = start(client, session, clip, channel, account, "youtube")

    def validate(*a):
        with Session() as other:
            youtube_auto.stop(other, other.get(LiveRecording, record.id))

    monkeypatch.setattr(youtube_auto, "validate_setup", validate)
    youtube_auto.tick()
    assert not remote and not session.scalar(select(PublishJob))


def test_setup_requires_channel_consent_and_public_permission(client, session, channel):
    payload = dict(
        url="https://www.twitch.tv/example",
        rights=True,
        youtube_auto=dict(enabled=True, channel_id=channel.id, privacy="public", consent=True),
    )
    assert client.post("/api/live", json=payload).status_code == 400
    update_settings(session, {"allow_public": True})
    assert client.post("/api/live", json={**payload, "auto_clip": False}).status_code == 422
    assert (
        client.post(
            "/api/live", json={**payload, "youtube_auto": {**payload["youtube_auto"], "consent": False}}
        ).status_code
        == 422
    )
    assert client.post("/api/live", json=payload).status_code == 200


def test_manual_worker_cannot_claim_live_job(client, session, clip, channel, account, remote):
    from backend.worker import publish_once

    start(client, session, clip, channel, account, "youtube")
    youtube_auto.queue_once()
    update_settings(session, {"publishing_enabled": True, "auto_publish": True})
    publish_once()
    assert not remote and session.scalar(select(PublishJob)).status == "pending"
    youtube_auto.tick()
    assert len(remote) == 1


def test_stop_during_token_refresh_prevents_init(
    client, session, clip, channel, account, remote, monkeypatch
):
    record = start(client, session, clip, channel, account, "youtube")

    def token(*a):
        with Session() as other:
            youtube_auto.stop(other, other.get(LiveRecording, record.id))
        return "test"

    monkeypatch.setattr(youtube, "access_token", token)
    youtube_auto.tick()
    assert not remote
    assert session.scalar(select(PublishJob)).status == "cancelled"


def test_explicit_future_schedule_is_honored(client, session, clip, channel, account, remote):
    start(client, session, clip, channel, account, "youtube")
    youtube_auto.queue_once()
    job = session.scalar(select(PublishJob))
    job.scheduled_at = now() + 3600
    session.commit()
    youtube_auto.tick()
    assert not remote
    job.scheduled_at = now() - 1
    session.commit()
    youtube_auto.tick()
    assert len(remote) == 1


def test_public_permission_revoked_after_job_edit(client, session, clip, channel, account, remote):
    record = start(client, session, clip, channel, account, "youtube")
    youtube_auto.queue_once()
    job = session.scalar(select(PublishJob))
    job.options = {**job.options, "privacy": "public"}
    session.commit()
    youtube_auto.tick()
    session.refresh(record)
    assert not remote and not record.auto_youtube_enabled
