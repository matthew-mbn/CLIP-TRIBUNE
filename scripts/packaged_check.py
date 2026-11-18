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
    network_downloads = []
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
        Path(report_path).write_text(
            json.dumps(
                dict(
                    ok=True,
                    pages=list(PAGES),
                    diagnostics=diagnostics,
                    rendered_clip=metadata,
                    clip_path=location["path"],
                    split_clip=split_metadata,
                    ads_preview=True,
                    ad_copy=True,
                    downloader_version=yt_dlp.version.__version__,
                    deno_bundled=True,
                    network_downloads=network_downloads,
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    finally:
        app.close()
