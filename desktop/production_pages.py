"""Обзор, очередь, библиотека и простой модуль анимации."""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import client, theme
from .base import Page, STATUSES, date


class QueuePage(Page):
    title = "Очередь обработки"
    subtitle = "Пауза останавливает запуск новых заданий. «Остановить всё» отменяет также текущий рендер."

    def __init__(self, parent, app):
        super().__init__(parent, app)
        row = self.toolbar()
        theme.button(row, "Продолжить очередь", lambda: self.control("resume-queue"), True)
        theme.button(row, "Пауза", lambda: self.control("pause"))
        theme.button(row, "Отменить выбранные", lambda: self.action("cancel"))
        theme.button(row, "Повторить ошибки", lambda: self.action("retry"))
        self.tree = theme.table(
            self,
            [
                ("id", "Задание"),
                ("kind", "Тип"),
                ("status", "Статус"),
                ("progress", "Прогресс"),
                ("message", "Подробности"),
            ],
            12,
        )
        self.tree.column("message", width=350)
        self.tree.bind("<<TreeviewSelect>>", self.details)
        self.info = theme.text(
            self,
            "Выберите задание, чтобы увидеть ошибку или результаты измерений.",
            muted=True,
            wraplength=850,
        )
        self.rows = {}

    def refresh(self, quiet=False):
        self.call("GET", "/jobs", callback=self.loaded, quiet=quiet)

    def loaded(self, rows):
        self.rows = {row["id"]: row for row in rows}
        kinds = {
            "clips": "Нарезки",
            "demo": "Тест",
            "animation": "Анимация",
            "import_remote": "Импорт",
            "download": "Скачивание",
            "ad_overlay": "Реклама",
        }
        theme.replace_rows(
            self.tree,
            [
                (
                    r["id"],
                    (
                        r["id"][:8],
                        kinds.get(r["kind"], r["kind"]),
                        STATUSES[r["status"]],
                        f"{r['progress']:.0f}%",
                        r["error"] or r["message"],
                    ),
                )
                for r in rows
            ],
        )

    def details(self, _=None):
        selected = self.tree.selection()
        if selected:
            row = self.rows[selected[0]]
            self.info.configure(text=(row["error"] or row["message"]) + "\nИзмерения: " + str(row["metrics"]))

    def control(self, action):
        self.call("POST", "/control/" + action, callback=lambda _: self.refresh())

    def action(self, action):
        for identity in self.selected(self.tree):
            self.call("POST", f"/jobs/{identity}/{action}", callback=lambda _: self.refresh())


class LibraryPage(Page):
    title = "Библиотека роликов"
    subtitle = "Готовые MP4, причины отбора и метаданные. Просмотр открывается в вашем видеопроигрывателе."

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.search = theme.field(self, "Поиск по заголовку")
        self.search.trace_add("write", lambda *_: self.draw())
        self.filter = theme.field(self, "Статус", "Все", ["Все", "Готово", "Опубликовано"])
        self.filter.trace_add("write", lambda *_: self.draw())
        self.rows = []
        self.tree = theme.table(
            self,
            [
                ("title", "Название"),
                ("duration", "Сек."),
                ("score", "Оценка"),
                ("size", "МБ"),
                ("date", "Создано"),
                ("status", "Статус"),
            ],
            7,
        )
        self.tree.column("title", width=330)
        self.tree.bind("<<TreeviewSelect>>", self.details)
        self.tree.bind("<Double-1>", lambda _: self.play())
        row = self.toolbar()
        theme.button(row, "▶ Смотреть", self.play, True)
        theme.button(row, "Сохранить как…", self.save)
        theme.button(row, "В публикацию", self.enqueue)
        theme.button(row, "Ещё из исходника", self.reedit)
        theme.button(row, "Удалить", self.delete)
        theme.button(self.toolbar(), "Добавить рекламу", self.advertise)
        preview = ttk.Frame(self)
        preview.pack(fill="both", expand=True, pady=10)
        self.preview = ttk.Label(preview)
        self.preview.pack(side="left", padx=(0, 12))
        self.preview_image = None
        self.info = tk.Text(
            preview,
            height=9,
            background=theme.PANEL,
            foreground=theme.WHITE,
            relief="flat",
            wrap="word",
            padx=16,
            pady=12,
            font=("Segoe UI", 10),
        )
        self.info.pack(fill="both", expand=True, pady=10)
        self.info.configure(state="disabled")

    def advertise(self):
        selected = self.selected(self.tree)
        if selected:
            self.app.show_page("Реклама")
            self.app.page.preselected = selected[0]

    def show_thumbnail(self, result):
        if result["thumbnail"].endswith(".png"):
            self.preview_image = tk.PhotoImage(file=result["thumbnail"]).subsample(2)
            self.preview.configure(image=self.preview_image)

    def refresh(self, quiet=False):
        self.call("GET", "/clips", callback=self.loaded, quiet=quiet)

    def loaded(self, rows):
        self.rows = rows
        self.draw()

    def draw(self):
        if not hasattr(self, "tree"):
            return
        visible = [
            r
            for r in self.rows
            if self.search.get().lower() in r["title"].lower()
            and (self.filter.get() == "Все" or STATUSES[r["status"]] == self.filter.get())
        ]
        theme.replace_rows(
            self.tree,
            [
                (
                    r["id"],
                    (
                        r["title"],
                        round(r["duration"]),
                        r["score"],
                        round(r["size"] / 1024**2, 1),
                        date(r["created_at"]),
                        STATUSES[r["status"]],
                    ),
                )
                for r in visible
            ],
        )

    def details(self, _=None):
        selected = self.tree.selection()
        if not selected:
            return
        clip = next(r for r in self.rows if r["id"] == selected[0])
        metadata = clip["metadata_json"]
        content = "\n".join(metadata.get("reasons", [])) + "\n\nЗаголовки:\n" + "\n".join(metadata["titles"])
        content += (
            "\n\n"
            + metadata["description"]
            + "\n"
            + metadata.get("warning", "")
            + "\n"
            + metadata.get("subtitle_status", "")
        )
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", content)
        self.info.configure(state="disabled")
        self.call("GET", f"/clips/{clip['id']}/location", callback=self.show_thumbnail, quiet=True)

    def play(self):
        selected = self.selected(self.tree)
        if selected:
            self.call(
                "GET", f"/clips/{selected[0]}/location", callback=lambda result: os.startfile(result["path"])
            )

    def save(self):
        selected = self.selected(self.tree)
        if selected:
            destination = filedialog.asksaveasfilename(
                parent=self, defaultextension=".mp4", filetypes=[("Видео MP4", "*.mp4")]
            )
            if destination:
                self.app.background(lambda: client.copy_clip(selected[0], destination))

    def enqueue(self):
        selected = self.selected(self.tree)
        if selected:
            self.call(
                "POST", "/publisher", dict(clip_ids=selected), lambda _: self.app.show_page("Публикация")
            )

    def reedit(self):
        selected = self.selected(self.tree)
        if selected:
            clip = next(row for row in self.rows if row["id"] == selected[0])
            if not clip["asset_id"]:
                self.app.show_page("Анимация")
                return
            self.app.show_page("Студия")
            self.app.page.preselected = clip["asset_id"]

    def delete(self):
        selected = self.selected(self.tree)
        if selected and messagebox.askyesno(
            "Удаление",
            f"Удалить {len(selected)} готовых роликов из библиотеки? Исходники сохранятся.",
            parent=self,
        ):
            for identity in selected:
                self.call("DELETE", f"/clips/{identity}", callback=lambda _: self.refresh())


class AnimationPage(Page):
    title = "Лаборатория анимации"
    subtitle = "Первый шаг к оригинальным мультфильмам."

    def __init__(self, parent, app):
        super().__init__(parent, app)
        illustration = tk.Canvas(self, bg=theme.PANEL, height=230, highlightthickness=0)
        illustration.pack(fill="x", pady=20)
        illustration.create_rectangle(260, 70, 330, 190, fill=theme.RED, outline="")
        illustration.create_rectangle(470, 70, 540, 190, fill=theme.WHITE, outline="")
        for x in (278, 307, 488, 517):
            illustration.create_oval(x, 95, x + 6, 101, fill=theme.BLACK, outline="")
        theme.text(self, "Два геометрических персонажа", font=("Segoe UI", 18, "bold"))
        theme.text(
            self,
            "Создаётся настоящий вертикальный MP4: 15 секунд, 720 × 1280.\nПерсонажи двигаются по заданным формулам. Это процедурная анимация.\nГенерация мультфильма по произвольному тексту ещё не реализована.",
            muted=True,
        )
        theme.button(self.toolbar(), "Создать анимацию", self.create, True)

    def create(self):
        self.call("POST", "/animation", callback=lambda _: self.app.show_page("Очередь"))
