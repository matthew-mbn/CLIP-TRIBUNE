"""Настоящие виджеты Tkinter с настоящим API, но без внешних сетевых вызовов."""

import time
import tkinter as tk

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
