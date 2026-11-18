"""Самопроверка собранного EXE на отдельной базе, без обращений к соцсетям.

Запускать с STORAGE_ROOT в новой временной папке и CLIP_TRIBUNE_PORT=18765.
Проверяет реальные службы EXE, multiprocessing, FFmpeg и страницы Tkinter.
"""

import json
import os
import time
from pathlib import Path

from desktop.client import request


def wait_job(identity, limit=180):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        job = next(r for r in request("GET", "/jobs") if r["id"] == identity)
        if job["status"] == "failed":
            raise RuntimeError(job["error"])
        if job["status"] == "ready":
            return job
        time.sleep(0.5)
    raise RuntimeError("Воркер EXE не закончил задачу вовремя")


def check_live(url):
    """Опциональная проверка разрешённого пользователем эфира в настоящем EXE."""
    from backend.video import probe

    item = request(
        "POST", "/live", dict(url=url, rights=True, segment_seconds=60, duration=15, min_score=0, height=720)
    )
    deadline = time.monotonic() + 210
    try:
        while time.monotonic() < deadline:
            row = next(r for r in request("GET", "/live") if r["id"] == item["id"])
            if row["status"] == "failed":
                raise RuntimeError(row["error"])
            clips = [c for c in request("GET", "/clips") if c["metadata_json"].get("live_id") == item["id"]]
            if clips:
                assert row["status"] == "recording", row["status"]
                path = request("GET", f"/clips/{clips[0]['id']}/location")["path"]
                metadata = probe(path)
                assert metadata["width"] == 720 and metadata["height"] == 1280
                assert metadata["audio"] and metadata["codec"] == "h264"
                return dict(clip_while_recording=True, recording_id=item["id"], clip=metadata, path=path)
            time.sleep(0.5)
        raise RuntimeError("Эфир записывается, но клип не появился за отведённое время")
    finally:
        request("POST", f"/live/{item['id']}/stop")
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            row = next(r for r in request("GET", "/live") if r["id"] == item["id"])
            if row["active_slot"] is None:
                break
            time.sleep(0.5)
        assert row["active_slot"] is None, "Запись не остановилась"


def run(report_path):
    if request("GET", "/sources")["assets"]:
        raise RuntimeError("Самопроверка допускается только на пустой тестовой базе")
    request("PUT", "/settings", {"onboarded": True, "resolution": "720"})
    diagnostics = request("GET", "/diagnostics")
    assert diagnostics["ffmpeg"] and diagnostics["ffprobe"]
    wait_job(request("POST", "/demo")["id"])
    # Кнопка demo сама создаёт задание нарезки: ждём его, не создаём дубль.
    job = next(row for row in request("GET", "/jobs") if row["kind"] == "clips")
    wait_job(job["id"])
    clips = request("GET", "/clips")
    assert clips and clips[0]["size"] > 1000
    from backend.video import probe

    location = request("GET", f"/clips/{clips[0]['id']}/location")
    metadata = probe(location["path"])
    assert (metadata["width"], metadata["height"]) == (1080, 1920)
    assert metadata["codec"] == "h264" and metadata["audio"]
    # Проверяем новые функции именно внутри EXE и его дочернего воркера.
    from backend.config import FFMPEG, STORAGE
    from backend.video import run as run_media
    from backend.downloads import deno_path
    import yt_dlp
    import yt_dlp_ejs
    from PIL import Image, ImageDraw

    assert yt_dlp.version.__version__ and yt_dlp_ejs.__file__
    assert deno_path() and "deno" in run_media([deno_path(), "--version"])
    creative = STORAGE / "temp" / "self-check-ad.png"
    picture = Image.new("RGB", (240, 120), "#00ff00")
    ImageDraw.Draw(picture).rectangle((40, 30, 200, 90), fill="#f04452")
    picture.save(creative)
    advert = request("POST", "/ads/import", {"path": str(creative)})
    config = dict(enabled=True, asset_id=advert["id"], mode="banner", position="center", width_percent=30)
    request("PUT", "/ads", config)
    preview = request("POST", "/ads/preview", {"config": config})
    assert len(preview["png"]) > 100
    ad_job = request("POST", "/ads/apply", {"config": config, "clip_id": clips[0]["id"]})
    wait_job(ad_job["id"])
    assert len(request("GET", "/clips")) == len(clips) + 1
    upper = STORAGE / "temp" / "self-check-upper.mp4"
    lower = STORAGE / "temp" / "self-check-lower.mp4"
    for path, color, length in [(upper, "blue", 16), (lower, "yellow", 3)]:
        run_media(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=180x320:r=30",
                "-t",
                str(length),
                "-c:v",
                "libx264",
                "-threads",
                "2",
                str(path),
            ]
        )
    imported = request("POST", "/sources/local", {"paths": [str(upper), str(lower)], "rights": True})[
        "assets"
    ]
    split_job = request(
        "POST",
        "/jobs",
        dict(
            asset_ids=[imported[0]["id"]],
            layout="split",
            secondary_asset_id=imported[1]["id"],
            count=1,
            duration=15,
            resolution="720",
        ),
    )[0]
    wait_job(split_job["id"])
    split_clip = next(clip for clip in request("GET", "/clips") if clip["job_id"] == split_job["id"])
    split_location = request("GET", f"/clips/{split_clip['id']}/location")
    split_metadata = probe(split_location["path"])
    assert (split_metadata["width"], split_metadata["height"]) == (720, 1280)
    assert split_clip["metadata_json"]["render_options"]["ad_source"]["asset_id"] == advert["id"]
    webcam_source = STORAGE / "temp" / "self-check-webcam.mp4"
    run_media(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=640x360:r=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-vf",
            "drawbox=x=480:y=240:w=160:h=120:color=red:t=fill",
            "-t",
            "16",
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-c:a",
            "aac",
            str(webcam_source),
        ]
    )
    webcam_asset = request("POST", "/sources/local", dict(paths=[str(webcam_source)], rights=True))["assets"][
        0
    ]
    webcam_frame = request("POST", "/webcam/frame", dict(asset_id=webcam_asset["id"]))
    assert webcam_frame["width"] == 640 and len(webcam_frame["png"]) > 100
    webcam_region = dict(x=0.75, y=2 / 3, width=0.25, height=1 / 3)
    webcam_job = request(
        "POST",
        "/jobs",
        dict(
            asset_ids=[webcam_asset["id"]],
            layout="webcam",
            webcam_region=webcam_region,
            count=1,
            duration=15,
            resolution="720",
        ),
    )[0]
    wait_job(webcam_job["id"])
    webcam_clip = next(c for c in request("GET", "/clips") if c["job_id"] == webcam_job["id"])
    webcam_path = request("GET", f"/clips/{webcam_clip['id']}/location")["path"]
    webcam_metadata = probe(webcam_path)
    assert (webcam_metadata["width"], webcam_metadata["height"], webcam_metadata["audio"]) == (
        720,
        1280,
        True,
    )
    check_frame = STORAGE / "temp" / "self-check-webcam-result.png"
    run_media([FFMPEG, "-v", "error", "-y", "-i", webcam_path, "-frames:v", "1", str(check_frame)])
    with Image.open(check_frame) as picture:
        upper_pixel, lower_pixel = (
            picture.convert("RGB").getpixel((360, 300)),
            picture.convert("RGB").getpixel((360, 960)),
        )
    assert upper_pixel[2] > 220 and upper_pixel[0] < 35
    assert lower_pixel[0] > 220 and lower_pixel[2] < 35
    network_downloads = []
    live_check = None
    if live_url := os.getenv("CLIP_TRIBUNE_CHECK_LIVE_URL"):
        live_check = check_live(live_url)
    if os.getenv("CLIP_TRIBUNE_CHECK_DOWNLOADS") == "1":
        # Явно включаем сетевую проверку; обычная самопроверка остаётся локальной.
        for platform, url in [
            ("YouTube", "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
            ("Twitch", "https://clips.twitch.tv/FaintLightGullWholeWheat"),
        ]:
            downloaded = request("POST", "/sources/download", dict(url=url, height=1080, rights=True))
            wait_job(downloaded["id"])
            network_downloads.append(platform)
    from desktop.app import Application
    from desktop.pages import PAGES
    import tkinter as tk

    # Тестовое подключение только для черновиков. Выбор Direct Post не должен
    # отправлять его фиктивный токен во внешний API или открывать окно ошибки.
    from backend.database import Session
    from backend.models import TikTokAccount, now
    from backend.security import encrypt

    with Session() as session:
        test_account = TikTokAccount(
            open_id="self-check-account",
            name="Permission check",
            tokens=encrypt(
                dict(
                    access_token="local-test-only",
                    scope="user.info.basic,video.upload",
                    expires_at=now() + 3600,
                )
            ),
        )
        session.add(test_account)
        session.commit()
        test_account_id = test_account.id
    scopes = request("GET", "/tiktok/accounts")[0]
    assert scopes["scopes"] == ["user.info.basic", "video.upload"] and "tokens" not in scopes
    try:
        request("GET", f"/tiktok/accounts/{test_account_id}/creator")
    except RuntimeError as error:
        assert "video.publish" in str(error) and "Подключить" in str(error)
    else:
        raise AssertionError("Direct Post must require video.publish")

    app = Application()
    app.withdraw()
    errors = []
    app.report_callback_exception = lambda *args: errors.append(str(args))
    try:
        for name in PAGES:
            app.show_page(name)
            deadline = time.monotonic() + 15

            def check():
                if not app.pending or time.monotonic() > deadline:
                    app.quit()
                else:
                    app.after(30, check)

            app.after(30, check)
            tk.Tk.mainloop(app)
            assert not app.pending, name
            assert not errors, errors
            if name == "Реклама":
                app.page.show_preview()
                deadline = time.monotonic() + 30
                app.after(30, check)
                tk.Tk.mainloop(app)
                assert not app.pending and app.page.preview_image
            if name == "Студия":
                app.page.layout_mode.set("Два ролика: верх / низ")
                assert app.page.split_panel.winfo_manager() == "pack"
                app.page.tree.selection_set(webcam_asset["id"])
                app.page.layout_mode.set("Видео + вебка · 50/50")
                app.page.webcam.load()
                deadline = time.monotonic() + 30
                app.after(30, check)
                tk.Tk.mainloop(app)
                editor = app.page.webcam.editor
                assert editor is not None
                editor.region = webcam_region
                editor.draw()
                assert editor.result_photo is not None
                editor.save()
                assert app.page.webcam.options()["webcam_region"] == webcam_region
            if name == "TikTok":
                app.page.mode.set("Прямая публикация")
                assert not app.pending and not app.page.creator_ready
                assert "video.publish" in app.page.creator_label.cget("text")
            if name == "Эфиры":
                assert app.page.youtube_auto.options() == {"enabled": False}
                app.page.youtube_auto.enabled.set(True)
                assert app.page.youtube_auto.body.winfo_manager() == "pack"
                app.page.youtube_auto.enabled.set(False)
                panel = app.page.tiktok_auto
                assert panel.options() == {"enabled": False}
                panel.enabled.set(True)
                assert not app.pending and not panel.ready
                assert "video.publish" in panel.creator_label.cget("text")
                panel.enabled.set(False)
        Path(report_path).write_text(
            json.dumps(
                dict(
                    ok=True,
                    pages=list(PAGES),
                    diagnostics=diagnostics,
                    rendered_clip=metadata,
                    clip_path=location["path"],
                    split_clip=split_metadata,
                    webcam_clip=webcam_metadata,
                    webcam_editor=True,
                    tiktok_permissions=True,
                    tiktok_auto_panel=True,
                    youtube_auto_panel=True,
                    ads_preview=True,
                    ad_copy=True,
                    downloader_version=yt_dlp.version.__version__,
                    deno_bundled=True,
                    network_downloads=network_downloads,
                    live_recording=live_check,
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    finally:
        app.close()
