"""Управление эфирами: окно отправляет команды, запись не выполняется в Tkinter."""

import os
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

from .captions import STYLES
from . import theme
from .ads_page import card
from .base import Page, date
from .webcam import WebcamPanel
from .live_tiktok import TikTokAutoPanel
from .live_youtube import YouTubeAutoPanel

STATUSES = {
    "pending": "Ожидание",
    "connecting": "Подключение",
    "recording": "● Запись",
    "reconnecting": "Переподключение",
    "stopping": "Остановка",
    "stopped": "Остановлено",
    "finished": "Эфир завершён",
    "failed": "Ошибка",
    "interrupted": "Прервано",
}
FRAMING = {
    "Размытый фон": "blur",
    "Обрезать в вертикаль": "crop",
    "Исходные пропорции": "original",
    "Видео + вебка · 50/50": "webcam",
    "Стрим с вебкой + геймплей": "split",
}


def duration(value):
    value = int(value)
    return f"{value // 3600:02}:{value // 60 % 60:02}:{value % 60:02}"


class LivePage(Page):
    title = "Прямые эфиры"
    subtitle = "YouTube Live и Twitch. Запись продолжается, пока готовые части превращаются в клипы."

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.rows = {}
        self.preselected = None
        connection = card(self)
        theme.text(connection, "01  /  Подключение к эфиру", font=("Segoe UI", 16, "bold"))
        self.url = theme.field(connection, "Ссылка YouTube Live или канал Twitch", "", stacked=True, width=75)
        theme.text(
            connection,
            "Для Twitch — twitch.tv/имя. Для YouTube — ссылка на текущую трансляцию.",
            muted=True,
            font=("Segoe UI", 11),
            wraplength=850,
        )
        self.rights = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            connection,
            text="У меня есть право на запись и использование этого эфира",
            variable=self.rights,
            font=("Segoe UI", 12),
        ).pack(anchor="w", pady=12)
        columns = ctk.CTkFrame(self, fg_color="transparent")
        columns.pack(fill="x")
        columns.columnconfigure((0, 1), weight=1, uniform="live")
        left = ctk.CTkFrame(columns, fg_color="transparent")
        right = ctk.CTkFrame(columns, fg_color="transparent")
        left.grid(row=0, column=0, sticky="new", padx=(0, 9))
        right.grid(row=0, column=1, sticky="new", padx=(9, 0))
        record = card(left)
        theme.text(record, "02  /  Запись", font=("Segoe UI", 16, "bold"))
        self.height = theme.field(record, "Качество, до", "720", ["720", "1080"], stacked=True, width=26)
        self.hours = theme.field(record, "Лимит времени, часов", "4", stacked=True, width=26)
        self.gigabytes = theme.field(record, "Лимит записи, ГБ", "20", stacked=True, width=26)
        self.segment = theme.field(
            record, "Анализировать каждые, сек.", "120", ["60", "120", "180", "300"], stacked=True, width=26
        )
        theme.text(
            record,
            "Части сохраняются на диске. После остановки их можно собрать в одну запись.",
            muted=True,
            wraplength=360,
            font=("Segoe UI", 11),
        )
        clips = card(right)
        theme.text(clips, "03  /  Автоматические нарезки", font=("Segoe UI", 16, "bold"))
        self.auto_clip = tk.BooleanVar(value=True)
        ctk.CTkSwitch(
            clips,
            text="Искать моменты во время эфира",
            variable=self.auto_clip,
            progress_color=theme.RED,
            font=("Segoe UI", 12),
        ).pack(anchor="w", pady=(4, 12))
        self.length = theme.field(
            clips, "Длина клипа, сек.", "30", ["15", "30", "45", "60"], stacked=True, width=26
        )
        self.count = theme.field(
            clips, "Клипов из одной части, до", "1", ["1", "2", "3"], stacked=True, width=26
        )
        self.score = theme.field(clips, "Порог отбора · 0–100", "25", stacked=True, width=26)
        self.framing = theme.field(
            clips, "Кадрирование", "Размытый фон", list(FRAMING), stacked=True, width=26
        )
        self.webcam = WebcamPanel(clips, self, self.webcam_source)
        from .gameplay import GameplayPanel

        self.gameplay = GameplayPanel(clips, self)
        self.webcam_anchor = ctk.CTkFrame(clips, fg_color="transparent", height=1)
        self.webcam_anchor.pack(fill="x")
        self.framing.trace_add("write", lambda *_: self.webcam_layout())
        theme.text(
            clips,
            "Отбор по динамике кадра и звуку. Выше порог — меньше клипов. Смысл момента проверьте перед публикацией.",
            muted=True,
            wraplength=360,
            font=("Segoe UI", 11),
        )
        extra = card(self)
        self.subject = theme.field(
            extra, "Тема для названий · можно оставить пустой", "", stacked=True, width=65
        )
        self.subtitles = tk.BooleanVar(value=False)
        self.ads = tk.BooleanVar(value=False)

        self.subtitle_style = theme.field(
            extra, "Стиль субтитров", "Крупный с обводкой", list(STYLES), stacked=True
        )
        ctk.CTkCheckBox(
            extra,
            text="Автоматические субтитры · локальное распознавание",
            variable=self.subtitles,
            font=("Segoe UI", 12),
        ).pack(anchor="w", pady=7)
        ctk.CTkCheckBox(
            extra, text="Добавлять рекламу из сохранённых настроек", variable=self.ads, font=("Segoe UI", 12)
        ).pack(anchor="w", pady=7)
        posting = card(self)
        theme.text(posting, "04  /  Автопубликация", font=("Segoe UI", 16, "bold"))
        theme.text(
            posting, "Включите TikTok, YouTube или оба сервиса. Настройки и лимиты независимы.", muted=True
        )
        self.tiktok_auto = TikTokAutoPanel(posting, app)
        self.tiktok_auto.pack(fill="x")
        self.youtube_auto = YouTubeAutoPanel(posting, app)
        self.youtube_auto.pack(fill="x", pady=(18, 0))
        controls = self.toolbar()
        self.start_button = theme.button(controls, "● Начать запись", self.start, True)
        theme.button(controls, "Остановить выбранную", self.stop)
        theme.button(controls, "Перейти к клипам", lambda: self.app.show_page("Библиотека"))
        self.notice = theme.text(
            self,
            "Один эфир за раз. Первый клип появится после накопления части и обработки.",
            muted=True,
            wraplength=900,
        )
        self.tree = theme.table(
            self,
            [
                ("title", "Эфир"),
                ("status", "Статус"),
                ("seconds", "Записано"),
                ("size", "Размер"),
                ("clips", "Клипы"),
                ("date", "Начало"),
            ],
            7,
        )
        self.tree.column("title", width=290)
        self.tree.bind("<<TreeviewSelect>>", self.details)
        row = self.toolbar()
        theme.button(row, "Открыть папку записи", self.open_folder)
        theme.button(row, "Собрать полную запись", self.export)
        auto_controls = self.toolbar()
        theme.button(auto_controls, "Стоп авто · TikTok", lambda: self.control_tiktok("stop"))
        theme.button(auto_controls, "Возобновить · TikTok", lambda: self.control_tiktok("resume"))
        theme.button(auto_controls, "Очередь TikTok", lambda: self.app.show_page("TikTok"))
        youtube_controls = self.toolbar()
        theme.button(youtube_controls, "Стоп авто · YouTube", lambda: self.control_youtube("stop"))
        theme.button(youtube_controls, "Возобновить · YouTube", lambda: self.control_youtube("resume"))
        theme.button(youtube_controls, "Очередь YouTube", lambda: self.app.show_page("Публикация"))
        self.info = theme.text(
            self,
            "Нарезки сохраняются в библиотеке. Автопубликация работает только при включении перед записью.",
            muted=True,
            wraplength=950,
        )

    def refresh(self, quiet=False):
        self.call("GET", "/live", callback=self.loaded, quiet=quiet)
        self.tiktok_auto.refresh(quiet=quiet)
        self.youtube_auto.refresh(quiet=quiet)

    def loaded(self, rows):
        self.rows = {row["id"]: row for row in rows}
        theme.replace_rows(
            self.tree,
            [
                (
                    r["id"],
                    (
                        r["title"],
                        STATUSES.get(r["status"], r["status"]),
                        duration(r["seconds"]),
                        f"{r['bytes'] / 1024**2:.1f} МБ",
                        f"{r['clips']} · в очереди {r['waiting']}",
                        date(r["started_at"]),
                    ),
                )
                for r in rows
            ],
        )
        active = next((r for r in rows if r["active_slot"] is not None), None)
        self.start_button.configure(state="disabled" if active else "normal")
        if active:
            self.notice.configure(text=active["message"])
        else:
            self.notice.configure(text="Запись не идёт. Сохранённые части и клипы остаются на компьютере.")
        if self.preselected and self.tree.exists(self.preselected):
            self.tree.selection_set(self.preselected)
            self.preselected = None
        self.details()

    def details(self, _=None):
        selected = self.tree.selection()
        if selected and selected[0] in self.rows:
            row = self.rows[selected[0]]
            text = (row["error"] or row["message"]) + "\n" + row["url"]
            if row["options"].get("tiktok_auto", {}).get("enabled"):
                state = row["options"].get("tiktok_auto_state", {})
                text += "\nTikTok: " + (
                    "автопубликация включена"
                    if row.get("auto_tiktok_enabled")
                    else "автопубликация остановлена"
                )
                text += " · " + state.get("message", "Ждём готовый клип")
                if state.get("error"):
                    text += "\n" + state["error"]
                if row.get("auto_tiktok_enabled") and state.get("next_at"):
                    text += "\nСледующая отправка не раньше: " + date(state["next_at"])
            if row["options"].get("youtube_auto", {}).get("enabled"):
                state = row.get("youtube_auto_state", {})
                text += "\nYouTube: " + (
                    "автопубликация включена"
                    if row.get("auto_youtube_enabled")
                    else "автопубликация остановлена"
                )
                text += " · " + state.get("message", "Ждём готовый клип")
                if state.get("error"):
                    text += "\n" + state["error"]
                if row.get("auto_youtube_enabled") and state.get("next_at"):
                    text += "\nСледующая отправка не раньше: " + date(state["next_at"])
            self.info.configure(text=text)

    def webcam_source(self):
        if not self.url.get().strip():
            raise ValueError("Сначала вставьте ссылку на эфир")
        if not self.rights.get():
            raise ValueError("Подтвердите право на запись и использование эфира")
        return dict(url=self.url.get().strip(), rights=True, height=int(self.height.get()))

    def webcam_layout(self):
        self.gameplay.pack_forget()
        if FRAMING[self.framing.get()] == "split":
            self.gameplay.pack(fill="x", before=self.webcam_anchor)
            self.gameplay.refresh()
        if FRAMING[self.framing.get()] == "webcam":
            self.webcam.pack(fill="x", before=self.webcam_anchor)
        else:
            self.webcam.pack_forget()

    def start(self):
        try:
            data = dict(
                url=self.url.get().strip(),
                rights=self.rights.get(),
                height=int(self.height.get()),
                max_hours=float(self.hours.get().replace(",", ".")),
                max_gb=int(self.gigabytes.get()),
                segment_seconds=int(self.segment.get()),
                auto_clip=self.auto_clip.get(),
                duration=int(self.length.get()),
                count=int(self.count.get()),
                min_score=int(self.score.get()),
                framing=FRAMING[self.framing.get()]
                if FRAMING[self.framing.get()] not in ("webcam", "split")
                else "blur",
                resolution=self.height.get(),
                theme=self.subject.get().strip(),
                subtitles=self.subtitles.get(),
                subtitle_style=STYLES[self.subtitle_style.get()],
                use_ads=self.ads.get(),
                tiktok_auto=self.tiktok_auto.options(),
                youtube_auto=self.youtube_auto.options(),
            )
            if FRAMING[self.framing.get()] == "webcam":
                data.update(self.webcam.options())
            if FRAMING[self.framing.get()] == "split":
                data.update(self.gameplay.options())
        except ValueError as error:
            messagebox.showerror("Параметры записи", str(error), parent=self)
            return
        self.call("POST", "/live", data, callback=self.started)

    def started(self, result):
        self.tiktok_auto.consent.set(False)
        self.youtube_auto.consent.set(False)
        self.preselected = result["id"]
        self.refresh()

    def stop(self):
        for identity in self.selected(self.tree):
            self.call("POST", f"/live/{identity}/stop", callback=lambda _: self.refresh())

    def control_tiktok(self, action):
        for identity in self.selected(self.tree):
            self.call("POST", f"/live/{identity}/tiktok/{action}", callback=lambda _: self.refresh())

    def control_youtube(self, action):
        for identity in self.selected(self.tree):
            self.call("POST", f"/live/{identity}/youtube/{action}", callback=lambda _: self.refresh())

    def open_folder(self):
        selected = self.selected(self.tree)
        if selected:
            self.call("GET", f"/live/{selected[0]}/location", callback=lambda r: os.startfile(r["path"]))

    def export(self):
        selected = self.selected(self.tree)
        if selected:
            self.call("POST", f"/live/{selected[0]}/export", callback=lambda _: self.exported())

    def exported(self):
        self.notice.configure(text="Сборка поставлена в очередь. Готовое видео появится в «Источниках».")
