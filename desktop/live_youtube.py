"""Настройки автопубликации YouTube для одной записи эфира."""

import tkinter as tk
import customtkinter as ctk
from . import theme
from .base import Page
from backend.schemas import YouTubeAutoInput

PRIVACY = {"Только я": "private", "По ссылке": "unlisted", "Все": "public"}


class YouTubeAutoPanel(Page):
    def __init__(self, parent, app):
        ctk.CTkFrame.__init__(self, parent, fg_color="transparent")
        self.app = app
        self.channels = {}
        self.enabled = tk.BooleanVar(value=False)
        ctk.CTkSwitch(
            self,
            text="Автоматически публиковать клипы в YouTube",
            variable=self.enabled,
            progress_color=theme.RED,
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w", pady=(8, 12))
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.channel = theme.field(self.body, "Канал YouTube", "Не подключён", ["Не подключён"], stacked=True)
        self.channel_box = self.body.winfo_children()[-1].winfo_children()[-1]
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x")
        theme.button(row, "Подключить канал", lambda: app.show_page("Публикация"))
        self.privacy = theme.field(self.body, "Видимость", "Только я", list(PRIVACY), stacked=True)
        theme.text(
            self.body,
            "Для видимости «Все» также включите разрешение публичной публикации в настройках.",
            muted=True,
            wraplength=880,
        )
        self.interval = theme.field(self.body, "Интервал, минут · 1–1440", "30", stacked=True)
        self.limit = theme.field(self.body, "Максимум отправок из записи · 1–100", "5", stacked=True)
        self.flags = {}
        for key, label in [
            ("made_for_kids", "Все клипы этой серии предназначены для детей"),
            ("synthetic", "Клипы содержат реалистично изменённый или синтетический контент"),
            ("paid_product_placement", "В клипах есть платное продвижение"),
        ]:
            value = self.flags[key] = tk.BooleanVar(value=False)
            ctk.CTkCheckBox(self.body, text=label, variable=value, font=("Segoe UI", 12)).pack(
                anchor="w", pady=6
            )
        self.consent = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self.body,
            text="Разрешаю отправку будущих клипов этой записи в YouTube без отдельных подтверждений",
            variable=self.consent,
            font=("Segoe UI", 12),
        ).pack(anchor="w", pady=(16, 8))
        theme.text(
            self.body,
            "Названия и описания берутся из готовых клипов. Лимиты YouTube и квоты API продолжают действовать. "
            "Ошибка приостановит только серию YouTube.",
            muted=True,
            wraplength=880,
        )
        self.enabled.trace_add("write", lambda *_: self.toggle())
        self.channel.trace_add("write", lambda *_: self.consent.set(False))

    def toggle(self):
        self.consent.set(False)
        if self.enabled.get():
            self.body.pack(fill="x")
        else:
            self.body.pack_forget()

    def refresh(self, quiet=False):
        self.call("GET", "/youtube/channels", callback=self.loaded, quiet=quiet)

    def loaded(self, rows):
        self.channels = {f"{r['name']} · {r['id'][:6]}": r["id"] for r in rows}
        choices = list(self.channels) or ["Не подключён"]
        self.channel_box.configure(values=choices)
        if self.channel.get() not in choices:
            self.channel.set(choices[0])

    def options(self):
        if not self.enabled.get():
            return {"enabled": False}
        identity = self.channels.get(self.channel.get())
        if not identity or not self.consent.get():
            raise ValueError("Выберите канал YouTube и разрешите отправку будущих клипов серии")
        return YouTubeAutoInput(
            enabled=True,
            channel_id=identity,
            consent=True,
            privacy=PRIVACY[self.privacy.get()],
            interval_minutes=int(self.interval.get()),
            max_posts=int(self.limit.get()),
            **{key: value.get() for key, value in self.flags.items()},
        ).model_dump()
