"""Серия эфир → клипы → TikTok: API подменён, реальные публикации невозможны."""

import httpx
import pytest
from sqlalchemy import select

from backend import tiktok, tiktok_auto
from backend.database import Session
from backend.models import LiveRecording, RenderedClip, TikTokJob, now, uid
from backend.schemas import TikTokAutoInput
from backend.security import decrypt, encrypt
from test_tiktok import account as account, clip as clip, CREATOR, ok


@pytest.fixture
def recording(session, account, clip):
    config = TikTokAutoInput(
        enabled=True, account_id=account.id, privacy_level="SELF_ONLY", consent=True
    ).model_dump()
    value = LiveRecording(
        url="https://www.twitch.tv/example",
        platform="twitch",
        status="recording",
        auto_tiktok_enabled=True,
        options=dict(duration=30, tiktok_auto=config),
    )
    session.add(value)
    session.flush()
    clip.metadata_json = {"live_id": value.id}
    session.commit()
    return value


@pytest.fixture
def remote(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs.get("json")))
        if "creator_info" in url:
            return ok(CREATOR)
        if "status/fetch" in url:
            return ok({"status": "PUBLISH_COMPLETE"})
        return ok({"publish_id": "auto-1", "upload_url": "https://open-upload.tiktokapis.com/video/"})

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "put", lambda *a, **k: httpx.Response(201))
    return calls


def jobs(session):
    session.expire_all()
    return session.scalars(select(TikTokJob)).all()


def another_clip(session, clip, live_id):
    item = RenderedClip(
        job_id=clip.job_id,
        path=clip.path,
        title="Следующий момент",
        duration=15,
        size=clip.size,
        sha256=uid(),
        metadata_json={"live_id": live_id},
    )
    session.add(item)
    session.commit()
    return item


def test_second_clip_waits_for_interval_and_remote_completion(session, recording, clip, remote, monkeypatch):
    tiktok.tick()
    first = jobs(session)[0]
    second = another_clip(session, clip, recording.id)
    session.refresh(recording)
    next_at = recording.options["tiktok_auto_state"]["next_at"]
    monkeypatch.setattr(tiktok_auto, "now", lambda: next_at + 1)
    tiktok_auto.queue_once()
    assert len(jobs(session)) == 1  # Предыдущий ещё обрабатывается в TikTok.
    tiktok.check_status(session, first)
    monkeypatch.setattr(tiktok_auto, "now", lambda: next_at - 1)
    tiktok_auto.queue_once()
    assert len(jobs(session)) == 1
    monkeypatch.setattr(tiktok_auto, "now", lambda: next_at + 1)
    tiktok.tick()
    all_jobs = jobs(session)
    assert len(all_jobs) == 2
    assert next(j for j in all_jobs if j.clip_id == second.id).status == "processing"
    assert sum("/init/" in url for url, _ in remote) == 2


def test_account_daily_cap_includes_other_series(session, recording, clip, account, remote):
    for _ in range(15):
        item = another_clip(session, clip, "other-series")
        session.add(TikTokJob(clip_id=item.id, account_id=account.id, status="published"))
    session.commit()
    tiktok_auto.queue_once()
    session.refresh(recording)
    assert not recording.auto_tiktok_enabled
    assert len(jobs(session)) == 15
    assert "24 часа" in recording.options["tiktok_auto_state"]["message"]


def test_unknown_result_must_be_checked_before_resume(client, session, recording, remote):
    tiktok_auto.queue_once()
    job = jobs(session)[0]
    job.status, job.publish_id = "interrupted", "unknown-result"
    recording.auto_tiktok_enabled = False
    session.commit()
    result = client.post(f"/api/live/{recording.id}/tiktok/resume")
    assert result.status_code == 400 and "проверьте статус" in result.json()["detail"]


def test_start_requires_consent_scope_and_matching_ad_disclosure(
    client, session, account, monkeypatch, remote
):
    config = TikTokAutoInput(
        enabled=True, account_id=account.id, privacy_level="SELF_ONLY", consent=True
    ).model_dump()
    data = dict(url="https://www.twitch.tv/example", rights=True, tiktok_auto=config)
    for key, value in [("consent", False), ("privacy_level", ""), ("account_id", "")]:
        assert (
            client.post("/api/live", json={**data, "tiktok_auto": {**config, key: value}}).status_code == 422
        )
    assert client.post("/api/live", json={**data, "auto_clip": False}).status_code == 422
    tokens = decrypt(account.tokens)
    account.tokens = encrypt({**tokens, "scope": "video.upload"})
    session.commit()
    result = client.post("/api/live", json=data)
    assert result.status_code == 400 and "video.publish" in result.text
    account.tokens = encrypt(tokens)
    session.commit()
    monkeypatch.setattr("backend.ads.snapshot", lambda *a, **k: {"id": "test-ad"})
    assert client.post("/api/live", json={**data, "use_ads": True}).status_code == 400
    result = client.post("/api/live", json=data)
    assert result.status_code == 200 and result.json()["auto_tiktok_enabled"]


def test_auto_pipeline_interval_idempotency_and_cap(session, recording, clip, remote):
    tiktok.tick()  # Готовый клип сам попадает в очередь и передаётся.
    job = jobs(session)[0]
    assert job.mode == "direct" and job.status == "processing"
    assert job.options["auto_live_id"] == recording.id
    init = [body for url, body in remote if "/init/" in url]
    assert len(init) == 1
    assert init[0]["post_info"]["title"] == clip.title
    assert init[0]["post_info"]["privacy_level"] == "SELF_ONLY"
    assert init[0]["post_info"]["disable_comment"] is True
    tiktok.tick()
    assert len(jobs(session)) == 1
    tiktok.check_status(session, job)
    assert job.status == "published"
    config = {**recording.options["tiktok_auto"], "max_posts": 1}
    recording.options = {**recording.options, "tiktok_auto": config}
    session.commit()
    tiktok_auto.queue_once()
    session.refresh(recording)
    assert not recording.auto_tiktok_enabled
    assert "лимит" in recording.options["tiktok_auto_state"]["message"]


def test_interval_and_foreign_clips_not_queued(session, recording, clip, remote):
    tiktok_auto.set_state(recording, next_at=now() + 600)
    session.commit()
    tiktok_auto.queue_once()
    assert not jobs(session)
    tiktok_auto.set_state(recording, next_at=0)
    clip.metadata_json = {"live_id": "different-stream"}
    session.commit()
    tiktok_auto.queue_once()
    assert not jobs(session)
    clip.metadata_json = {"live_id": recording.id}
    session.commit()
    tiktok_auto.queue_once()
    tiktok_auto.queue_once()
    assert len(jobs(session)) == 1


def test_init_error_pauses_without_replay(session, recording, monkeypatch, remote):
    original = httpx.post

    def post(url, **kwargs):
        if "/init/" in url:
            remote.append((url, None))
            return httpx.Response(
                400, json={"error": {"code": "invalid_params", "message": "privacy_level invalid"}}
            )
        return original(url, **kwargs)

    monkeypatch.setattr(httpx, "post", post)
    tiktok.tick()
    job = jobs(session)[0]
    assert job.status == "failed" and "privacy_level invalid" in job.error
    session.refresh(recording)
    assert not recording.auto_tiktok_enabled and recording.status == "recording"
    tiktok.tick()
    assert sum("/init/" in url for url, _ in remote) == 1


@pytest.mark.parametrize("action", ["stop", "tiktok/stop", "global"])
def test_stop_cancels_pending_and_future_posts(client, session, recording, remote, action):
    tiktok_auto.queue_once()
    assert len(jobs(session)) == 1
    path = "/api/control/stop" if action == "global" else f"/api/live/{recording.id}/{action}"
    assert client.post(path).status_code == 200
    tiktok.tick()
    session.refresh(recording)
    assert not recording.auto_tiktok_enabled
    assert jobs(session)[0].status == "cancelled"
    assert not any("/init/" in url for url, _ in remote)


def test_stop_during_creator_query_cannot_enqueue(session, recording, monkeypatch, remote):
    def creator(*args):
        with Session() as other:
            tiktok_auto.stop(other, other.get(LiveRecording, recording.id))
        return CREATOR

    monkeypatch.setattr(tiktok, "creator_info", creator)
    tiktok_auto.queue_once()
    assert not jobs(session)


def test_stop_after_claim_during_creator_query_cannot_init(session, recording, monkeypatch, remote):
    tiktok_auto.queue_once()

    def creator(*args):
        with Session() as other:
            tiktok_auto.stop(other, other.get(LiveRecording, recording.id))
        return CREATOR

    monkeypatch.setattr(tiktok, "creator_info", creator)
    tiktok.tick()
    assert jobs(session)[0].status == "cancelled"
    assert not any("/init/" in url for url, _ in remote)


def test_resume_does_not_retry_failed_clip(client, session, recording, remote):
    tiktok_auto.queue_once()
    job = jobs(session)[0]
    job.status, job.error, job.updated_at = "failed", "failure", now()
    tiktok_auto.pause_failed(session, job, job.error)
    session.commit()
    assert client.post(f"/api/live/{recording.id}/tiktok/resume").status_code == 200
    tiktok_auto.queue_once()
    assert len(jobs(session)) == 1 and jobs(session)[0].status == "failed"
    session.refresh(recording)
    assert recording.auto_tiktok_enabled


def test_remote_processing_failure_pauses_immediately(session, recording, monkeypatch, remote):
    tiktok.tick()
    job = jobs(session)[0]
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: ok({"status": "FAILED", "fail_reason": "processing_failed"})
    )
    tiktok.check_status(session, job)
    session.refresh(recording)
    assert not recording.auto_tiktok_enabled


def test_error_detail_and_utf16_caption_limit():
    from backend.schemas import TikTokPublishInput

    with pytest.raises(RuntimeError) as failure:
        tiktok.decoded(
            httpx.Response(
                400,
                json={
                    "error": {
                        "code": "invalid_params",
                        "message": "bad title access_token=hidden https://example.test/?secret=x",
                    }
                },
            )
        )
    assert (
        "bad title" in str(failure.value)
        and "hidden" not in str(failure.value)
        and "secret=x" not in str(failure.value)
    )
    with pytest.raises(ValueError, match="UTF-16"):
        TikTokPublishInput(clip_id="clip", account_id="account", title="😀" * 1101)
