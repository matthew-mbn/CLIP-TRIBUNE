"""Проверяем пользовательские действия и границы доверия HTTP API."""

import json

from sqlalchemy import select

from backend.models import ContentProject, RenderJob, SourceAsset


def test_project_creation(client, session):
    result = client.post("/api/projects", json={"name": "Моя серия"})
    assert result.status_code == 200
    assert session.get(ContentProject, result.json()["id"]).name == "Моя серия"


def test_import_local_and_duplicate(client, sample_video):
    first = client.post("/api/sources/local", json={"paths": [str(sample_video)], "rights": True}).json()
    second = client.post("/api/sources/local", json={"paths": [str(sample_video)], "rights": True}).json()
    assert first["assets"][0]["id"] == second["assets"][0]["id"]
    assert first["assets"][0]["metadata_json"]["width"] == 640
    assert "path" not in first["assets"][0]


def test_upload(client, sample_video):
    with sample_video.open("rb") as stream:
        result = client.post(
            "/api/sources/upload",
            files={"file": ("sample.mp4", stream, "video/mp4")},
            data={"rights": "true"},
        )
    assert result.status_code == 200
    assert result.json()["rights"] is True


def test_invalid_file(client, tmp_path):
    path = tmp_path / "fake.mp4"
    path.write_text("not a video")
    result = client.post("/api/sources/local", json={"paths": [str(path)]}).json()
    assert not result["assets"] and result["errors"]


def test_unknown_extension(client, tmp_path):
    path = tmp_path / "script.exe"
    path.write_bytes(b"hello")
    result = client.post("/api/sources/local", json={"paths": [str(path)]}).json()
    assert "Поддерживаются" in result["errors"][0]["error"]


def test_job_requires_rights(client, asset, session):
    asset.rights = False
    session.commit()
    result = client.post("/api/jobs", json={"asset_ids": [asset.id]})
    assert result.status_code == 400
    assert "прав" in result.json()["detail"]


def test_job_cancel_retry(client, asset, session):
    result = client.post("/api/jobs", json={"asset_ids": [asset.id], "duration": 15, "count": 2})
    assert result.status_code == 200
    identity = result.json()[0]["id"]
    assert client.post(f"/api/jobs/{identity}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/jobs/{identity}/retry").json()["status"] == "pending"
    session.expire_all()
    assert session.get(RenderJob, identity).progress == 0


def test_same_asset_cannot_run_twice(client, asset):
    assert client.post("/api/jobs", json={"asset_ids": [asset.id]}).status_code == 200
    assert client.post("/api/jobs", json={"asset_ids": [asset.id]}).status_code == 400


def test_explicit_demo_resumes_paused_queue(client):
    client.post("/api/control/pause")
    client.post("/api/demo")
    assert not client.get("/api/dashboard").json()["queue_paused"]


def test_automatic_publish_needs_explicit_setting(client):
    assert not client.get("/api/publisher").json()["enabled"]
    client.put("/api/settings", json={"auto_publish": True})
    assert client.get("/api/publisher").json()["enabled"]
    client.post("/api/publishing/stop")
    assert not client.get("/api/settings").json()["auto_publish"]


def test_control_stop(client, asset):
    client.post("/api/jobs", json={"asset_ids": [asset.id]})
    client.post("/api/control/start")
    assert client.get("/api/dashboard").json()["production"] == "running"
    client.post("/api/control/stop")
    assert client.get("/api/jobs").json()[0]["status"] == "cancelled"
    assert client.get("/api/dashboard").json()["queue_paused"]


def test_local_token_and_origin(client):
    assert client.get("/api/settings", headers={"X-Clip-Tribune": "wrong"}).status_code == 403
    assert client.put("/api/settings", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/settings", headers={"Host": "evil.example"}).status_code == 400


def test_secret_not_returned(client):
    response = client.put("/api/settings/secrets", json={"values": {"YOUTUBE_API_KEY": "secret-test-value"}})
    assert response.status_code == 200
    settings = client.get("/api/settings").json()
    assert settings["configured"]["YOUTUBE_API_KEY"]
    assert "secret-test-value" not in json.dumps(settings)


def test_settings_validation(client):
    assert client.put("/api/settings", json={"workers": 0}).status_code == 422
    assert client.post("/api/jobs", json={"asset_ids": ["missing"], "duration": 1}).status_code == 422


def test_read_pages_empty(client):
    for endpoint in (
        "dashboard",
        "settings",
        "sources",
        "jobs",
        "clips",
        "trends",
        "youtube/channels",
        "publisher",
        "projects",
    ):
        assert client.get("/api/" + endpoint).status_code == 200


def test_folder_watch(client, tmp_path, sample_video, session):
    import shutil
    from backend.worker import scheduler_tick

    shutil.copyfile(sample_video, tmp_path / "new.mp4")
    result = client.post(
        "/api/sources/folder", json={"path": str(tmp_path), "rights": True, "watching": True}
    )
    assert result.status_code == 200
    seen = {}
    scheduler_tick(seen)
    assert session.scalar(select(SourceAsset)) is None
    scheduler_tick(seen)
    assert session.scalar(select(SourceAsset)) is not None
    client.delete("/api/sources/folders/" + result.json()["id"])
    assert not client.get("/api/sources").json()["folders"][0]["watching"]
