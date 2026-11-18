"""Проверка размеров init и фактических PUT, включая остаток последней части."""

from pathlib import Path
import httpx
import pytest
from sqlalchemy import select
from backend import tiktok
from backend.models import TikTokJob
from backend.schemas import TikTokPublishInput
from test_tiktok import account as account, clip as clip, CREATOR, ok

CHUNK_ERROR = "TikTok: invalid_params (HTTP 400) · The chunk size is invalid"


@pytest.mark.parametrize("mode", ["inbox", "direct"])
@pytest.mark.parametrize("size", [4_194_304, 15_000_001, 20_971_519, 64_000_000, 64_000_001, 70_000_123])
def test_init_matches_all_transmitted_bytes(session, account, clip, monkeypatch, size, mode):
    # Разрежённый файл экономит запись на диск; чтение всё равно идёт настоящим upload.
    with Path(clip.path).open("wb") as stream:
        stream.write(b"A")
        stream.seek(size - 1)
        stream.write(b"Z")
    # Метаданные размера намеренно устарели: uploader обязан проверить сам файл.
    declared, parts = {}, []

    def remote(url, **kwargs):
        if "creator_info" in url:
            return ok(CREATOR)
        info = kwargs["json"]["source_info"]
        declared.update(info)
        assert info["video_size"] == size
        count, chunk = info["total_chunk_count"], info["chunk_size"]
        if count == 1:
            assert chunk == size
            assert size <= 64_000_000
        else:
            assert 5_000_000 <= chunk <= 64_000_000
            assert count == size // chunk
        return ok({"publish_id": "checked", "upload_url": "https://open-upload.tiktokapis.com/video/"})

    def put(url, **kwargs):
        block, headers = kwargs["content"], kwargs["headers"]
        offset = sum(parts)
        last = len(parts) + 1 == declared["total_chunk_count"]
        assert len(block) == (size - offset if last else declared["chunk_size"])
        assert len(block) <= 128_000_000
        assert headers["Content-Length"] == str(len(block))
        assert headers["Content-Range"] == f"bytes {offset}-{offset + len(block) - 1}/{size}"
        if not parts:
            assert block[:1] == b"A"
        if last:
            assert block[-1:] == b"Z"
        parts.append(len(block))
        return httpx.Response(201 if last else 206)

    monkeypatch.setattr(httpx, "post", remote)
    monkeypatch.setattr(httpx, "put", put)
    job = tiktok.enqueue(
        session,
        TikTokPublishInput(
            clip_id=clip.id, account_id=account.id, mode=mode, consent=True, privacy_level="SELF_ONLY"
        ),
    )
    tiktok.tick()
    session.refresh(job)
    assert job.status == "processing", job.error
    assert sum(parts) == size and len(parts) == declared["total_chunk_count"]


def failed_job(session, account, clip, error=CHUNK_ERROR, publish_id=None):
    job = TikTokJob(
        clip_id=clip.id, account_id=account.id, status="failed", error=error, publish_id=publish_id
    )
    session.add(job)
    session.commit()
    return job


def test_explicit_retry_reuses_rejected_job_and_rechecks_consent(client, session, account, clip):
    job = failed_job(session, account, clip)
    payload = dict(clip_id=clip.id, account_id=account.id, mode="inbox", consent=False)
    assert client.post("/api/tiktok/jobs", json=payload).status_code == 400
    payload["consent"] = True
    result = client.post("/api/tiktok/jobs", json=payload)
    assert result.status_code == 200 and result.json()["id"] == job.id
    assert result.json()["status"] == "pending" and result.json()["error"] is None
    assert client.post("/api/tiktok/jobs", json=payload).status_code == 400
    assert len(session.scalars(select(TikTokJob)).all()) == 1


@pytest.mark.parametrize(
    "error,publish_id",
    [
        ("Не удалось связаться с TikTok", None),
        (CHUNK_ERROR, "already-accepted"),
        ("TikTok: invalid_params (HTTP 400) · Unknown error", None),
    ],
)
def test_ambiguous_or_accepted_post_cannot_be_retried(client, session, account, clip, error, publish_id):
    failed_job(session, account, clip, error, publish_id)
    assert (
        client.post(
            "/api/tiktok/jobs", json=dict(clip_id=clip.id, account_id=account.id, consent=True)
        ).status_code
        == 400
    )


def test_rejected_job_stays_failed_until_user_resubmits(session, account, clip):
    job = failed_job(session, account, clip)
    tiktok.tick()
    session.refresh(job)
    assert job.status == "failed"


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.ConnectError, httpx.ProxyError])
def test_network_diagnostic_never_prints_exception_url(session, account, monkeypatch, failure):
    def request(*args, **kwargs):
        raise failure("https://example.test/?access_token=private-value")

    monkeypatch.setattr(httpx, "post", request)
    with pytest.raises(RuntimeError) as error:
        tiktok.post(session, account, "/post/publish/inbox/video/init/", {})
    assert failure.__name__ in str(error.value)
    assert "private-value" not in str(error.value) and "https://" not in str(error.value)
