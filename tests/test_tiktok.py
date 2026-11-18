"""Контрактные тесты TikTok. Сеть заменена: реальные аккаунты не затрагиваются."""

import hashlib
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from backend import tiktok
from backend.config import STORAGE
from backend.models import OAuthState, RenderJob, RenderedClip, TikTokAccount, TikTokJob, now, uid
from backend.schemas import TikTokPublishInput
from backend.security import decrypt, encrypt

CREATOR = dict(
    creator_nickname="Test creator",
    privacy_level_options=["SELF_ONLY", "PUBLIC_TO_EVERYONE"],
    max_video_post_duration_sec=60,
    comment_disabled=False,
    duet_disabled=True,
    stitch_disabled=False,
)


@pytest.fixture
def account(session):
    value = TikTokAccount(
        open_id="test-user",
        name="Test creator",
        tokens=encrypt(
            dict(
                access_token="access",
                refresh_token="refresh",
                expires_at=now() + 3600,
                scope="user.info.basic,video.upload,video.publish",
            )
        ),
    )
    session.add(value)
    session.commit()
    return value


@pytest.fixture
def clip(session):
    path = STORAGE / "clips" / (uid() + ".mp4")
    path.write_bytes(b"fake-mp4-http-fixture")
    job = RenderJob(status="ready")
    session.add(job)
    session.flush()
    value = RenderedClip(
        job_id=job.id, path=str(path), title="Test clip", duration=15, size=path.stat().st_size, sha256=uid()
    )
    session.add(value)
    session.commit()
    return value


def ok(data):
    return httpx.Response(200, json={"data": data, "error": {"code": "ok"}})


def test_desktop_pkce_hex_and_scoped_state(client, session):
    client.put(
        "/api/settings/secrets",
        json={"values": {"TIKTOK_CLIENT_KEY": "client", "TIKTOK_CLIENT_SECRET": "secret"}},
    )
    result = client.post("/api/tiktok/connect", json={"mode": "inbox"})
    assert result.status_code == 200
    query = parse_qs(urlparse(result.json()["url"]).query)
    state = session.get(OAuthState, query["state"][0])
    assert query["code_challenge"] == [hashlib.sha256(state.verifier.encode()).hexdigest()]
    assert query["scope"] == ["user.info.basic,video.upload"]
    assert client.get("/api/youtube/callback", params={"state": state.state, "code": "x"}).status_code == 400
    assert (
        client.get("/api/tiktok/callback", params={"state": state.state, "error": "denied"}).status_code
        == 200
    )
    assert (
        client.get("/api/tiktok/callback", params={"state": state.state, "error": "denied"}).status_code
        == 400
    )


def test_refresh_rotation_saved(session, account, monkeypatch):
    account.tokens = encrypt(dict(access_token="old", refresh_token="r1", expires_at=0))
    session.commit()
    monkeypatch.setattr(tiktok, "credentials", lambda: {"client_key": "client", "client_secret": "s"})
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: httpx.Response(
            200, json={"access_token": "new", "refresh_token": "r2", "expires_in": 7200}
        ),
    )
    assert tiktok.access_token(session, account) == "new"
    assert decrypt(account.tokens)["refresh_token"] == "r2"


def test_direct_validation_and_consent(client, account, clip, monkeypatch):
    monkeypatch.setattr(tiktok, "creator_info", lambda *a: CREATOR)
    data = dict(clip_id=clip.id, account_id=account.id, mode="direct", consent=False)
    assert client.post("/api/tiktok/jobs", json=data).status_code == 400
    data["consent"] = True
    assert client.post("/api/tiktok/jobs", json=data).status_code == 400
    data.update(privacy_level="SELF_ONLY", allow_duet=True)
    assert client.post("/api/tiktok/jobs", json=data).status_code == 400
    data.update(allow_duet=False, commercial=True, brand_content=True)
    assert client.post("/api/tiktok/jobs", json=data).status_code == 400
    data.update(privacy_level="PUBLIC_TO_EVERYONE")
    assert client.post("/api/tiktok/jobs", json=data).status_code == 200
    assert client.post("/api/tiktok/jobs", json=data).status_code == 400
    assert client.delete(f"/api/clips/{clip.id}").status_code == 400


@pytest.mark.parametrize("size", [1, 4_000_000, 10_485_760, 50_000_123, 70_000_000, 4 * 1024**3])
def test_chunk_rules(size):
    chunk, count = tiktok.chunk_plan(size)
    assert count == size // chunk
    final = size - chunk * (count - 1)
    assert final <= 128 * 1024**2
    assert count == 1 or 5 * 1024**2 <= chunk <= 64 * 1024**2


@pytest.mark.parametrize("mode", ["inbox", "direct"])
def test_upload_and_remote_status(session, account, clip, monkeypatch, mode):
    requests, chunks = [], []

    def remote(url, **kwargs):
        requests.append((url, kwargs.get("json")))
        if "creator_info" in url:
            return ok(CREATOR)
        if "status/fetch" in url:
            return ok({"status": "SEND_TO_USER_INBOX" if mode == "inbox" else "PUBLISH_COMPLETE"})
        return ok(
            {"publish_id": "p1", "upload_url": "https://open-upload.tiktokapis.com/video/?secret=hidden"}
        )

    def put(url, **kwargs):
        chunks.append(kwargs)
        return httpx.Response(201)

    monkeypatch.setattr(httpx, "post", remote)
    monkeypatch.setattr(httpx, "put", put)
    job = tiktok.enqueue(
        session,
        TikTokPublishInput(
            clip_id=clip.id, account_id=account.id, mode=mode, privacy_level="SELF_ONLY", consent=True
        ),
    )
    tiktok.tick()
    session.refresh(job)
    assert job.status == "processing"  # Переданный файл ещё не опубликован.
    assert job.progress == 100
    assert chunks[0]["headers"]["Content-Range"] == f"bytes 0-{clip.size - 1}/{clip.size}"
    assert "hidden" not in job.upload_url
    tiktok.check_status(session, job)
    assert job.status == ("inbox" if mode == "inbox" else "published")
    init = next(body for url, body in requests if "/init/" in url)
    assert ("post_info" in init) == (mode == "direct")
    if mode == "direct":
        assert init["post_info"]["disable_comment"] is True


def test_error_does_not_reinitialize_post(session, account, clip, monkeypatch):
    calls = []
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: (
            calls.append(a[0])
            or ok(
                {"publish_id": "p1", "upload_url": "https://open-upload.tiktokapis.com/video/?token=hidden"}
            )
        ),
    )
    monkeypatch.setattr(httpx, "put", lambda *a, **k: httpx.Response(500))
    job = tiktok.enqueue(session, TikTokPublishInput(clip_id=clip.id, account_id=account.id, consent=True))
    tiktok.tick()
    tiktok.tick()
    session.refresh(job)
    assert job.status == "interrupted"
    assert len(calls) == 1
    assert "hidden" not in job.error


def test_global_stop_cancels_tiktok(client, session, account, clip):
    job = TikTokJob(clip_id=clip.id, account_id=account.id)
    session.add(job)
    session.commit()
    assert client.post("/api/control/stop").status_code == 200
    session.refresh(job)
    assert job.status == "cancelled"


def test_tiktok_requires_local_token(client):
    assert client.get("/api/tiktok/accounts", headers={"X-Clip-Tribune": ""}).status_code == 403


def test_oauth_callback_keeps_tokens_encrypted(session, monkeypatch):
    session.add(OAuthState(state="tt_test", verifier="verifier", expires_at=now() + 60))
    session.commit()
    monkeypatch.setattr(tiktok, "credentials", lambda: {"client_key": "client", "client_secret": "secret"})
    calls = []

    def exchange(url, **kwargs):
        calls.append(kwargs["data"])
        return httpx.Response(
            200,
            json=dict(
                access_token="private-access",
                refresh_token="private-refresh",
                open_id="creator",
                expires_in=7200,
                scope="user.info.basic,video.upload",
            ),
        )

    monkeypatch.setattr(httpx, "post", exchange)
    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: ok({"user": {"display_name": "Creator", "open_id": "creator"}})
    )
    account = tiktok.oauth_callback(session, "tt_test", "authorization-code")
    assert calls[0]["code_verifier"] == "verifier"
    assert account.name == "Creator" and "private-access" not in account.tokens
    assert decrypt(account.tokens)["refresh_token"] == "private-refresh"
    with pytest.raises(ValueError):
        tiktok.oauth_callback(session, "tt_test", "authorization-code")


def test_reject_external_upload_host(session, account, clip, monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: ok({"publish_id": "p1", "upload_url": "https://evil.example/file"})
    )
    monkeypatch.setattr(
        httpx, "put", lambda *a, **k: pytest.fail("Нельзя отправлять файл на посторонний адрес")
    )
    job = tiktok.enqueue(session, TikTokPublishInput(clip_id=clip.id, account_id=account.id, consent=True))
    tiktok.tick()
    session.refresh(job)
    assert job.status == "interrupted"
    assert "недопустимый адрес" in job.error
