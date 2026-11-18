"""Google заменён MockTransport: тесты никогда не загружают реальные видео."""

import json

import httpx
import pytest

from backend import youtube
from backend.database import update_settings
from backend.models import OAuthState, PublishJob, RenderJob, RenderedClip, YouTubeChannel, now
from backend.security import decrypt, encrypt, inside, public_url


def test_encryption():
    encrypted = encrypt({"refresh_token": "secret"})
    assert "secret" not in encrypted
    assert decrypt(encrypted) == {"refresh_token": "secret"}


def test_oauth_state_single_use(session):
    session.add(OAuthState(state="good", verifier="verifier", expires_at=now() + 60))
    session.commit()
    with pytest.raises(ValueError):
        youtube.consume_state(session, "bad")
    assert youtube.consume_state(session, "good") == "verifier"
    with pytest.raises(ValueError):
        youtube.consume_state(session, "good")


def test_oauth_expired(client, session):
    session.add(OAuthState(state="expired", verifier="a", expires_at=1))
    session.commit()
    assert client.get("/api/youtube/callback?state=expired&code=fake").status_code == 400


def test_pkce(client):
    client.put("/api/settings/secrets", json={"values": {"GOOGLE_CLIENT_ID": "test-client"}})
    response = client.post("/api/youtube/connect")
    assert response.status_code == 200
    assert "code_challenge_method=S256" in response.json()["url"]


def test_quota_separate_buckets(session):
    update_settings(session, {"quota_upload": 1, "quota_search": 1})
    youtube.reserve_quota(session, "upload")
    with pytest.raises(youtube.QuotaExceeded):
        youtube.reserve_quota(session, "upload")
    youtube.reserve_quota(session, "search")
    status = youtube.quota_status(session)
    assert status["buckets"]["upload"]["remaining"] == 0
    assert status["buckets"]["general"]["remaining"] == 10000


@pytest.mark.parametrize("reason", ["quotaExceeded", "uploadLimitExceeded", "rateLimitExceeded"])
def test_quota_errors(reason):
    with pytest.raises(youtube.QuotaExceeded):
        youtube.google_error(httpx.Response(403, json={"error": {"errors": [{"reason": reason}]}}))


def test_path_traversal():
    with pytest.raises(ValueError):
        inside("../outside.mp4")


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/a.mp4",
        "https://127.0.0.1/a.mp4",
        "https://[::1]/a.mp4",
        "https://user:pass@example.com/a.mp4",
    ],
)
def test_remote_ssrf(url):
    with pytest.raises(ValueError):
        public_url(url)


def test_resumable_upload_mock(session, tmp_path, monkeypatch):
    path = tmp_path / "small.mp4"
    path.write_bytes(b"fake-video-for-http-test")
    render = RenderJob()
    channel = YouTubeChannel(
        youtube_id="mock-channel",
        name="Тестовый канал",
        tokens=encrypt({"access_token": "mock-token", "refresh_token": "refresh", "expires_at": now() + 600}),
    )
    session.add_all([render, channel])
    session.commit()
    clip = RenderedClip(
        job_id=render.id,
        title="Тест",
        path=str(path),
        duration=15,
        size=path.stat().st_size,
        metadata_json={"description": "Тестовый ролик", "hashtags": ["Shorts"]},
        sha256="mock-sha",
    )
    session.add(clip)
    session.commit()
    job = PublishJob(clip_id=clip.id, channel_id=channel.id, options={"privacy": "private"})
    session.add(job)
    session.commit()
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            assert json.loads(request.content)["status"]["privacyStatus"] == "private"
            return httpx.Response(200, headers={"Location": "https://www.googleapis.com/upload/session/mock"})
        if request.headers["Content-Range"].startswith("bytes */"):
            return httpx.Response(308)
        assert request.content == path.read_bytes()
        return httpx.Response(200, json={"id": "mock-video-id"})

    original_client = httpx.Client
    monkeypatch.setattr(
        youtube.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler))
    )
    assert youtube.upload(session, job, clip) == "mock-video-id"
    assert len(calls) == 3
    assert job.upload_url and "googleapis" not in job.upload_url


def test_public_upload_requires_setting(client):
    response = client.post("/api/publisher", json={"clip_ids": ["missing"], "privacy": "public"})
    assert response.status_code == 400 and "публичную" in response.json()["detail"]
