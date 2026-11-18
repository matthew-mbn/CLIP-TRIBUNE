"""Настоящие виджеты Tkinter с настоящим API, но без внешних сетевых вызовов."""

import time
import tkinter as tk
from types import SimpleNamespace

from backend.database import update_settings
from desktop.app import Application
from desktop.pages import PAGES


def drain(app, seconds=10):
    deadline = time.monotonic() + seconds

    def check():
        if app.pending == 0 or time.monotonic() >= deadline:
            app.quit()
        else:
            app.after(20, check)

    app.after(20, check)
    # Для коротких тестовых циклов пропускаем повторную инициализацию окна CTk.
    tk.Tk.mainloop(app)
    assert app.pending == 0, (app.current_page, app.pending)


def test_all_pages_navigation_and_jobs(client, session, asset, monkeypatch):
    update_settings(session, {"onboarded": True})
    errors = []
    monkeypatch.setattr("tkinter.messagebox.showerror", lambda *args, **kwargs: errors.append(args))

    def api(method, path, data=None):
        response = client.request(method, "/api" + path, json=data)
        if response.is_error:
            raise RuntimeError(str(response.json()))
        return response.json()

    app = Application(api=api)
    app.withdraw()
    try:
        drain(app)
        for name in PAGES:
            app.show_page(name)
            drain(app)
            assert app.page.winfo_exists()
            assert app.current_page == name
        app.show_page("Студия")
        drain(app)
        app.page.tree.selection_set(asset.id)
        app.page.duration.set("15")
        app.page.create()
        drain(app)
        assert app.current_page == "Очередь"
        assert len(app.page.tree.get_children()) == 1
        identity = app.page.tree.get_children()[0]
        app.page.tree.selection_set(identity)
        app.page.action("cancel")
        drain(app)
        assert app.page.rows[identity]["status"] == "cancelled"
        assert not errors, errors
    finally:
        app.close()
        del app
        # TestClient остаётся в этом процессе: не отдаём очистку UI его потоку.
        import gc

        gc.collect()


def test_live_auto_setup_preserves_selection_and_stops_series(client, session, monkeypatch):
    from backend import tiktok
    from backend.models import TikTokAccount, now
    from backend.security import encrypt
    from test_tiktok import CREATOR

    update_settings(session, {"onboarded": True})
    account = TikTokAccount(
        open_id="auto-ui",
        name="Auto test",
        tokens=encrypt(
            dict(
                scope="video.publish",
                access_token="test",
                refresh_token="test",
                expires_at=now() + 3600,
            )
        ),
    )
    session.add(account)
    session.commit()
    monkeypatch.setattr(tiktok, "creator_info", lambda *a: CREATOR)
    errors = []
    monkeypatch.setattr("tkinter.messagebox.showerror", lambda *a, **k: errors.append(a))

    def api(method, path, data=None):
        response = client.request(method, "/api" + path, json=data)
        if response.is_error:
            raise RuntimeError(str(response.json()))
        return response.json()

    app = Application(api=api)
    app.withdraw()
    try:
        drain(app)
        app.show_page("Эфиры")
        drain(app)
        page, panel = app.page, app.page.tiktok_auto
        assert panel.options() == {"enabled": False}
        panel.enabled.set(True)
        drain(app)
        assert panel.ready and panel.privacy.get() == "Выберите видимость"
        assert panel.switches["allow_duet"].cget("state") == "disabled"
        panel.privacy.set("Только я")
        panel.consent.set(True)
        panel.caption.set("{title} #стрим")
        page.refresh()
        drain(app)
        assert panel.privacy.get() == "Только я" and panel.consent.get()
        assert panel.options()["caption_template"] == "{title} #стрим"
        page.url.set("https://www.twitch.tv/example")
        page.rights.set(True)
        page.start()
        drain(app)
        row = next(iter(page.rows.values()))
        assert row["auto_tiktok_enabled"] and not panel.consent.get()
        assert "включена" in page.info.cget("text")
        page.control_tiktok("stop")
        drain(app)
        assert not page.rows[row["id"]]["auto_tiktok_enabled"]
        assert not errors, errors
    finally:
        app.close()
        del app
        import gc

        gc.collect()


def test_webcam_selection_studio_live_and_changed_source(client, session, asset, monkeypatch):
    update_settings(session, {"onboarded": True})
    errors = []
    monkeypatch.setattr("tkinter.messagebox.showerror", lambda *args, **kwargs: errors.append(args))

    def api(method, path, data=None):
        response = client.request(method, "/api" + path, json=data)
        if response.is_error:
            raise RuntimeError(str(response.json()))
        return response.json()

    app = Application(api=api)
    app.withdraw()
    try:
        drain(app)
        app.show_page("Студия")
        drain(app)
        page = app.page
        page.tree.selection_set(asset.id)
        page.layout_mode.set("Видео + вебка · 50/50")
        assert page.webcam.winfo_manager() == "pack" and not page.split_panel.winfo_manager()
        page.webcam.load()
        drain(app)
        editor = page.webcam.editor
        assert editor is not None
        editor.update_idletasks()
        editor.draw()
        x, y, width, height = editor.image_box
        # Выделяем в обратном направлении: справа снизу к левому верхнему углу.
        editor.begin(SimpleNamespace(x=x + width, y=y + height))
        editor.finish(SimpleNamespace(x=x + width * 0.75, y=y + height * 0.5))
        assert editor.region == dict(x=0.75, y=0.5, width=0.25, height=0.5)
        assert editor.result_photo is not None
        editor.save()
        assert page.webcam.options()["layout"] == "webcam"
        page.create()
        drain(app)
        assert app.current_page == "Очередь"
        app.show_page("Эфиры")
        drain(app)
        page = app.page
        page.framing.set("Видео + вебка · 50/50")
        assert page.webcam.winfo_manager() == "pack"
        page.url.set("https://www.twitch.tv/example")
        page.rights.set(True)
        page.webcam.saved(page.url.get(), dict(webcam_region=dict(x=0.75, y=0.5, width=0.25, height=0.5)))
        page.url.set("https://www.twitch.tv/another")
        import pytest

        with pytest.raises(ValueError, match="Выделите"):
            page.webcam.options()
        page.url.set("https://www.twitch.tv/example")
        page.start()
        drain(app)
        assert next(iter(page.rows.values()))["options"]["layout"] == "webcam"
        assert not errors, errors
    finally:
        app.close()
        del app
        import gc

        gc.collect()


def test_tiktok_scope_switch_and_reauthorization(client, session, monkeypatch):
    from backend import tiktok
    from backend.models import TikTokAccount, now
    from backend.security import encrypt

    update_settings(session, {"onboarded": True})
    tokens = dict(
        access_token="test",
        refresh_token="test",
        scope="user.info.basic,video.upload",
        expires_at=now() + 3600,
    )
    account = TikTokAccount(open_id="test", name="Test creator", tokens=encrypt(tokens))
    session.add(account)
    session.commit()
    calls, errors = [], []
    monkeypatch.setattr("tkinter.messagebox.showerror", lambda *a, **k: errors.append(a))
    monkeypatch.setattr(
        tiktok,
        "creator_info",
        lambda *a: (
            calls.append(True)
            or dict(
                creator_nickname="Test creator",
                max_video_post_duration_sec=60,
                privacy_level_options=["SELF_ONLY"],
                comment_disabled=False,
                duet_disabled=True,
                stitch_disabled=False,
            )
        ),
    )

    def api(method, path, data=None):
        response = client.request(method, "/api" + path, json=data)
        if response.is_error:
            raise RuntimeError(str(response.json()))
        return response.json()

    app = Application(api=api)
    app.withdraw()
    try:
        drain(app)
        app.show_page("TikTok")
        drain(app)
        page = app.page
        page.mode.set("Прямая публикация")
        drain(app)
        assert not calls and not page.creator_ready
        assert "video.publish" in page.creator_label.cget("text")
        assert "Подключить" in page.creator_label.cget("text")
        assert page.submit.cget("state") == "disabled"
        # OAuth меняет токен той же записи: имя и id остаются прежними.
        account.tokens = encrypt(
            {**tokens, "scope": "user.info.basic,video.publish", "expires_at": now() + 7200}
        )
        session.commit()
        page.refresh()
        drain(app)
        assert calls == [True] and page.creator_ready
        page.privacy.set("Только я")
        page.consent.set(True)
        page.refresh()
        drain(app)
        assert calls == [True] and page.privacy.get() == "Только я" and page.consent.get()
        page.mode.set("Черновик в TikTok")
        drain(app)
        assert "video.upload" in page.creator_label.cget("text")
        assert not errors, errors
    finally:
        app.close()
        del app
        import gc

        gc.collect()
