"""Настоящие MP4: пауза, продолжение, субтитры и экспорт без перезаписи."""

from pathlib import Path
import array
import pytest
from sqlalchemy import select
from backend import ads, captions, video, speech
from backend.models import RenderedClip, RenderJob
from backend.schemas import AdOptions
from backend.security import file_hash
from backend.worker import process_job
from test_composition import make_color, frame, near, composition_media as composition_media


def clip_row(session, path):
    job = RenderJob(status="ready")
    session.add(job)
    session.flush()
    clip = RenderedClip(
        job_id=job.id,
        title="TWITCH: example",
        path=str(path),
        thumbnail="",
        duration=video.probe(path)["duration"],
        size=path.stat().st_size,
        score=50,
        sha256=file_hash(path),
        metadata_json=dict(titles=["TWITCH: example"], description="test"),
    )
    session.add(clip)
    session.commit()
    return clip


@pytest.mark.parametrize("start", [0, 1])
def test_ad_freezes_and_resumes_without_losing_source(session, composition_media, tmp_path, start):
    _, _, creative = composition_media
    source = make_color(
        tmp_path / "changing.mp4",
        "blue",
        duration=4,
        extra=",drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='gte(t,2)'",
        frequency=440,
    )
    asset = ads.import_ad(session, creative)
    ad = ads.snapshot(
        session, AdOptions(enabled=True, asset_id=asset.id, start=start, sound=False).model_dump()
    )
    output = tmp_path / "paused.mp4"
    result = video.render(
        source,
        output,
        dict(start=0, duration=4),
        dict(resolution="360", framing="crop", ad_source=ad),
        video.probe(source),
    )
    assert result["duration"] == pytest.approx(5, abs=0.15)
    # Вне вставки виден замерший синий кадр; смена на белый сдвигается на секунду.
    near(frame(output, start + 0.5, tmp_path).getpixel((20, 20)), (0, 0, 255))
    near(frame(output, 2.5, tmp_path).getpixel((20, 20)), (0, 0, 255))
    near(frame(output, 3.5, tmp_path).getpixel((20, 20)), (255, 255, 255))
    pcm = tmp_path / "silence.pcm"
    video.run(
        [
            video.FFMPEG,
            "-v",
            "error",
            "-y",
            "-ss",
            str(start + 0.2),
            "-i",
            str(output),
            "-t",
            "0.4",
            "-vn",
            "-f",
            "f32le",
            "-ac",
            "1",
            str(pcm),
        ]
    )
    assert max(abs(x) for x in array.array("f", pcm.read_bytes())) < 0.002


def test_export_multiple_without_overwrite(client, session, composition_media, tmp_path):
    clip = clip_row(session, composition_media[0])
    payload = dict(folder=str(tmp_path / "chosen"), clip_ids=[clip.id])
    first = client.post("/api/editing/export", json=payload).json()["paths"][0]
    second = client.post("/api/editing/export", json=payload).json()["paths"][0]
    assert first != second and file_hash(first) == file_hash(second) == file_hash(clip.path)
    assert client.put("/api/editing/folder", json={"folder": payload["folder"]}).status_code == 200
    assert client.get("/api/editing/folder").json()["folder"] == str(Path(payload["folder"]).resolve())


def test_caption_editor_timing_hidden_and_clean_master(client, session, composition_media, tmp_path):
    clip = clip_row(session, composition_media[0])
    original = file_hash(clip.path)
    data = dict(
        style="bold",
        cues=[dict(start=1, end=2, text="HELLO"), dict(start=2, end=3, text="HIDDEN", enabled=False)],
    )
    response = client.post(f"/api/editing/captions/{clip.id}/render", json=data)
    assert response.status_code == 200, response.text
    assert client.delete(f"/api/clips/{clip.id}").status_code == 400
    job_id = response.json()["id"]
    process_job(job_id)
    session.expire_all()
    assert session.get(RenderJob, job_id).status == "ready", session.get(RenderJob, job_id).error
    result = session.scalar(select(RenderedClip).where(RenderedClip.id != clip.id))
    assert file_hash(clip.path) == original
    assert captions.clean_source(result).is_file()
    assert captions.load(result).cues[1].enabled is False
    for second, visible in [(0.5, False), (1.5, True), (2.5, False)]:
        image = frame(result.path, second, tmp_path)
        assert any(r > 150 for r, g, b in image.get_flattened_data()) == visible
    invalid = {**data, "cues": [dict(start=0, end=50, text="too long")]}
    assert client.post(f"/api/editing/captions/{clip.id}/render", json=invalid).status_code == 400
    preview = client.post(f"/api/editing/captions/{result.id}/preview", json={**data, "second": 1.5})
    assert preview.status_code == 200 and preview.json()["png"]


def test_subtitles_shift_and_hide_during_ad(session, composition_media, tmp_path):
    ad = ads.import_ad(session, composition_media[2])
    options = dict(
        ad_source=ads.snapshot(session, AdOptions(enabled=True, asset_id=ad.id, start=1).model_dump())
    )
    out = tmp_path / "subtitles.mp4"
    captions.prepare(out, [dict(start=0.5, end=2, text="phrase")], 0, 4, options)
    import json

    cues = json.loads(out.with_suffix(".captions.json").read_text())["cues"]
    assert [(c["start"], c["end"]) for c in cues] == [(0.5, 1), (2, 3)]


def test_live_gameplay_snapshot(client, session, asset):
    request = dict(
        url="https://www.twitch.tv/example",
        rights=True,
        layout="split",
        secondary_asset_id=asset.id,
        split_fit="fit",
    )
    result = client.post("/api/live", json=request)
    assert result.status_code == 200, result.text
    assert result.json()["options"]["split_source"]["id"] == asset.id
    assert result.json()["options"]["split_fit"] == "fit"


def test_caption_recognition_job(client, session, composition_media, monkeypatch):
    clip = clip_row(session, composition_media[0])
    monkeypatch.setattr(speech, "transcribe", lambda *a: [dict(start=0, end=1, text="Real service stub")])
    job = client.post(f"/api/editing/captions/{clip.id}/recognize").json()
    process_job(job["id"])
    assert client.get(f"/api/editing/captions/{clip.id}").json()["cues"][0]["text"] == "Real service stub"


def test_live_preview_reuses_connection_until_closed(client, monkeypatch, tmp_path):
    from backend import live_preview
    from PIL import Image

    calls = []

    class Process:
        ended = False

        def __init__(self, command, **kwargs):
            calls.append(command)
            Image.new("RGB", (320, 180), "blue").save(command[-1])

        def poll(self):
            return 0 if self.ended else None

        def terminate(self):
            self.ended = True

        def wait(self, **kwargs):
            return 0

    monkeypatch.setattr(
        live_preview,
        "resolve_stream",
        lambda *a: (
            "stream",
            [dict(video=True, audio=True, url="https://media.example/live", headers={})],
            {},
        ),
    )
    monkeypatch.setattr(live_preview.subprocess, "Popen", Process)
    body = dict(url="https://www.twitch.tv/example", rights=True)
    assert client.post("/api/webcam/live-preview", json={**body, "rights": False}).status_code == 400
    identity = client.post("/api/webcam/live-preview", json=body).json()["id"]
    try:
        for _ in range(3):
            assert client.get(f"/api/webcam/live-preview/{identity}").json()["png"]
        assert len(calls) == 1  # Повторные кадры не начинают новую сессию с рекламой.
    finally:
        assert client.delete(f"/api/webcam/live-preview/{identity}").status_code == 200
    assert identity not in live_preview.sessions


def test_live_preview_frames_advance_without_reconnect(client, monkeypatch, tmp_path):
    import time
    import base64
    import io
    from PIL import Image
    from backend import live_preview

    source = make_color(
        tmp_path / "stream.mp4",
        "blue",
        duration=5,
        extra=",drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='gte(t,2)'",
    )
    monkeypatch.setattr(live_preview, "resolve_stream", lambda *a: ("test", [dict(video=True)], {}))
    monkeypatch.setattr(live_preview, "stream_inputs", lambda *a: ["-re", "-i", str(source)])
    identity = client.post(
        "/api/webcam/live-preview", json=dict(url="https://www.twitch.tv/example", rights=True)
    ).json()["id"]
    seen_blue = seen_white = False
    try:
        deadline = time.monotonic() + 9
        while time.monotonic() < deadline:
            result = client.get(f"/api/webcam/live-preview/{identity}").json()
            if result.get("png"):
                with Image.open(io.BytesIO(base64.b64decode(result["png"]))) as image:
                    r, g, b = image.convert("RGB").getpixel((90, 90))
                seen_blue |= b > 220 and r < 30
                seen_white |= r > 220 and g > 220
            if seen_blue and seen_white:
                break
            time.sleep(0.2)
        assert seen_blue and seen_white
    finally:
        client.delete(f"/api/webcam/live-preview/{identity}")


def test_editor_and_live_gameplay_widgets(client, session, asset, monkeypatch):
    from backend.database import update_settings
    from desktop.app import Application
    from desktop.captions import CaptionEditor
    from test_desktop import drain

    update_settings(session, {"onboarded": True})
    clip = clip_row(session, Path(asset.path))
    errors = []
    monkeypatch.setattr("tkinter.messagebox.showerror", lambda *a, **k: errors.append(a))

    def api(method, path, data=None):
        response = client.request(method, "/api" + path, json=data)
        if response.is_error:
            raise RuntimeError(response.text)
        return response.json()

    app = Application(api=api)
    app.withdraw()
    editor = None
    try:
        drain(app)
        app.show_page("Эфиры")
        drain(app)
        page = app.page
        page.framing.set("Стрим с вебкой + геймплей")
        drain(app)
        page.gameplay.asset.set(next(iter(page.gameplay.assets)))
        assert page.gameplay.options()["secondary_asset_id"] == asset.id
        assert page.gameplay.options()["split_fit"] == "fit"
        editor = CaptionEditor(app, app, clip.id)
        editor.withdraw()
        drain(app)
        editor.add()
        editor.text.set("Changed")
        editor.start.set("1")
        editor.end.set("2")
        editor.enabled.set(False)
        assert editor.apply()
        assert editor.data()["cues"] == [dict(start=1, end=2, text="Changed", enabled=False)]
        editor.preview()
        drain(app)
        assert editor.photo is not None
        editor.render()
        drain(app)
        assert not errors, errors
    finally:
        if editor:
            editor.destroy()
        app.close()
        import gc

        gc.collect()
