"""Мастер первого запуска — обычное дочернее окно Tkinter."""

import tkinter as tk
from tkinter import filedialog, ttk

from . import theme


class Onboarding(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Добро пожаловать в CLIP TRIBUNE")
        x = max(0, app.winfo_rootx() + (app.winfo_width() - 720) // 2)
        y = max(0, app.winfo_rooty() + (app.winfo_height() - 680) // 2)
        self.geometry(f"720x680+{x}+{y}")
        self.configure(bg=theme.BLACK)
        self.transient(app)
        panel = ttk.Frame(self, padding=30)
        panel.pack(fill="both", expand=True)
        theme.logo(panel, 58, theme.BLACK).pack(anchor="w", pady=(0, 20))
        theme.text(panel, "Ваша первая нарезка", font=("Segoe UI", 24, "bold"))
        theme.text(panel, "1. Выберите папки.  2. Проверьте FFmpeg.  3. Запустите тест.", muted=True)
        self.source = theme.field(panel, "Папка исходников")
        ttk.Button(panel, text="Выбрать исходники", command=lambda: self.choose(self.source)).pack(anchor="e")
        self.output = theme.field(panel, "Папка копий результатов")
        ttk.Button(panel, text="Выбрать результаты", command=lambda: self.choose(self.output)).pack(
            anchor="e"
        )
        self.resolution = theme.field(panel, "Разрешение", "1080", ["720", "1080"])
        self.diagnostics = theme.text(panel, "Проверяем FFmpeg…", muted=True)
        theme.text(
            panel,
            "YouTube и AI подключаются позже в «Настройках».\nПубликация по умолчанию выключена. Тест использует созданное FFmpeg видео.",
            muted=True,
        )
        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", pady=10)
        theme.button(buttons, "Сохранить и выполнить тест", lambda: self.finish(True), True)
        theme.button(buttons, "Начать без теста", lambda: self.finish(False))
        app.async_call("GET", "/diagnostics", callback=self.show_diagnostics)

    def choose(self, variable):
        path = filedialog.askdirectory(parent=self)
        if path:
            variable.set(path)

    def show_diagnostics(self, result):
        self.diagnostics.configure(
            text="FFmpeg готов к работе"
            if result["ffmpeg"] and result["ffprobe"]
            else "FFmpeg не найден: запустите setup_windows.ps1"
        )

    def finish(self, test):
        def saved(_):
            if test:
                self.app.async_call("POST", "/demo", callback=lambda _: self.app.show_page("Очередь"))
            self.destroy()

        self.app.async_call(
            "PUT",
            "/settings",
            dict(
                onboarded=True,
                source_folder=self.source.get(),
                output_folder=self.output.get(),
                resolution=self.resolution.get(),
            ),
            callback=saved,
        )
