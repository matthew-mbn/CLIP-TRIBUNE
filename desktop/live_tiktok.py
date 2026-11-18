"""Настройки одной серии автопубликаций. Секреты в виджеты не передаются."""

import tkinter as tk
import customtkinter as ctk

from . import theme
from .base import Page
from .tiktok_page import PRIVACY
from backend.schemas import TikTokAutoInput


class TikTokAutoPanel(Page):
    def __init__(self, parent, app):
        # Используем доставку ответов и очистку Tk-переменных общего Page,
        # но рисуем компактную карточку внутри страницы эфира.
        ctk.CTkFrame.__init__(self, parent, fg_color="transparent")
        self.app = app
        self.accounts = {}
        self.revision = 0
        self.ready = False
        self.enabled = tk.BooleanVar(value=False)
        ctk.CTkSwitch(
            self,
            text="Автоматически публиковать клипы в TikTok",
            variable=self.enabled,
            progress_color=theme.RED,
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w", pady=(0, 12))
        theme.text(
            self,
            "Экспериментальный режим · запись → отбор моментов → клипы → TikTok",
            muted=True,
            wraplength=880,
        )
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        theme.text(
            self.body,
            "Ролики отправляются без просмотра и подтверждения каждого клипа. Этот режим не соответствует "
            "процессу согласия App Review TikTok. Без аудита Direct Post доступен только в режиме «Только я».",
            muted=True,
            wraplength=880,
            font=("Segoe UI", 12),
        )
        self.account = theme.field(self.body, "Аккаунт", "Не подключён", ["Не подключён"], stacked=True)
        self.account_box = self.body.winfo_children()[-1].winfo_children()[-1]
        self.creator_label = theme.text(self.body, "", muted=True, wraplength=880)
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x")
        theme.button(row, "Подключить аккаунт", lambda: app.show_page("TikTok"))
        theme.button(row, "Обновить параметры", self.load_creator)
        self.privacy = theme.field(
            self.body,
            "Видимость всех клипов серии",
            "Выберите видимость",
            ["Выберите видимость"],
            stacked=True,
        )
        self.privacy_box = self.body.winfo_children()[-1].winfo_children()[-1]
        self.caption = theme.field(
            self.body, "Подпись · {title} заменяется названием клипа", "{title}", stacked=True, width=65
        )
        self.interval = theme.field(
            self.body, "Интервал между отправками, минут · 10–1440", "30", stacked=True
        )
        self.limit = theme.field(self.body, "Максимум отправок из этой записи · 1–15", "5", stacked=True)
        self.flags, self.switches = {}, {}
        for key, label in [
            ("allow_comment", "Разрешить комментарии"),
            ("allow_duet", "Разрешить дуэты"),
            ("allow_stitch", "Разрешить сшивание"),
            ("commercial", "В клипах есть реклама или продвижение бренда"),
            ("brand_organic", "Продвигается мой бренд"),
            ("brand_content", "Продвигается чужой бренд · Paid partnership"),
            ("synthetic", "Отметить клипы как контент, созданный ИИ"),
        ]:
            value = self.flags[key] = tk.BooleanVar(value=False)
            widget = self.switches[key] = ctk.CTkCheckBox(
                self.body, text=label, variable=value, font=("Segoe UI", 12)
            )
            widget.pack(anchor="w", pady=6)
        self.consent = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self.body,
            text="Разрешаю отправку будущих клипов этой записи без отдельных подтверждений",
            variable=self.consent,
            font=("Segoe UI", 12),
        ).pack(anchor="w", pady=(16, 8))
        theme.text(
            self.body,
            "При отправке действуют Music Usage Confirmation и правила рекламы TikTok. "
            "Ошибка приостановит отправку. Кнопка «Остановить всё» остановит всю цепочку. "
            "Программа должна оставаться открытой.",
            muted=True,
            wraplength=880,
            font=("Segoe UI", 12),
        )
        self.enabled.trace_add("write", lambda *_: self.toggle())
        self.account.trace_add("write", lambda *_: self.load_creator())

    def toggle(self):
        if self.enabled.get():
            self.body.pack(fill="x")
        else:
            self.body.pack_forget()
        self.load_creator()

    def refresh(self, quiet=False):
        self.call("GET", "/tiktok/accounts", callback=self.loaded, quiet=quiet)

    def loaded(self, rows):
        old = self.accounts.get(self.account.get())
        self.accounts = {f"{r['name']} · {r['id'][:6]}": r for r in rows}
        choices = list(self.accounts) or ["Не подключён"]
        self.account_box.configure(values=choices)
        if self.account.get() not in choices:
            self.account.set(choices[0])
        else:
            new = self.accounts.get(self.account.get())

            def signature(r):
                return (r.get("scopes"), r.get("expires_at")) if r else None

            if signature(old) != signature(new):
                self.load_creator()

    def load_creator(self):
        self.revision += 1
        revision = self.revision
        self.ready = False
        self.consent.set(False)
        self.privacy.set("Выберите видимость")
        self.privacy_box.configure(values=["Выберите видимость"])
        for key in ("allow_comment", "allow_duet", "allow_stitch"):
            self.flags[key].set(False)
            self.switches[key].configure(state="disabled")
        if not self.enabled.get():
            return
        account = self.accounts.get(self.account.get())
        if not account or "video.publish" not in account.get("scopes", []):
            self.creator_label.configure(
                text="В разделе TikTok выберите «Прямая публикация», нажмите «Подключить» и выдайте video.publish."
            )
            return
        self.creator_label.configure(text="Получаем доступную видимость и ограничения аккаунта…")

        def loaded(info):
            if revision != self.revision:
                return
            self.ready = True
            self.creator_label.configure(
                text=f"Автор: {info['creator_nickname']} · до {info['max_video_post_duration_sec']} сек."
            )
            self.privacy_box.configure(values=[PRIVACY.get(p, p) for p in info["privacy_level_options"]])
            for name in ("comment", "duet", "stitch"):
                self.switches["allow_" + name].configure(
                    state="disabled" if info[name + "_disabled"] else "normal"
                )

        self.call("GET", f"/tiktok/accounts/{account['id']}/creator", callback=loaded)

    def options(self):
        if not self.enabled.get():
            return {"enabled": False}
        if not self.ready:
            raise ValueError("Сначала подключите TikTok с video.publish и получите параметры аккаунта")
        privacy = next((key for key, value in PRIVACY.items() if value == self.privacy.get()), "")
        if not privacy or not self.consent.get():
            raise ValueError("Выберите видимость и разрешите автоматическую отправку клипов этой записи")
        return TikTokAutoInput(
            enabled=True,
            account_id=self.accounts[self.account.get()]["id"],
            privacy_level=privacy,
            caption_template=self.caption.get(),
            interval_minutes=int(self.interval.get()),
            max_posts=int(self.limit.get()),
            consent=True,
            **{key: value.get() for key, value in self.flags.items()},
        ).model_dump()
