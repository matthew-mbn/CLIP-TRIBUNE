"""Экран TikTok: пользователь видит ролик, аккаунт и параметры перед отправкой."""

import os
import tkinter as tk
import webbrowser
from tkinter import messagebox

import customtkinter as ctk

from . import theme
from .base import Page, STATUSES

MODES = {"Черновик в TikTok": "inbox", "Прямая публикация": "direct"}
PRIVACY = {
    "PUBLIC_TO_EVERYONE": "Все",
    "MUTUAL_FOLLOW_FRIENDS": "Друзья",
    "FOLLOWER_OF_CREATOR": "Подписчики",
    "SELF_ONLY": "Только я",
}


class TikTokPage(Page):
    title = "Публикация в TikTok"
    subtitle = "Ваш ролик. Ваш аккаунт. Последнее слово — за вами."

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.account_ids, self.clip_ids, self.rows = {}, {}, {}
        self.creator_ready = False
        columns = ctk.CTkFrame(self, fg_color="transparent")
        columns.pack(fill="x", pady=(6, 14))
        columns.grid_columnconfigure((0, 1), weight=1, uniform="publish")
        left = ctk.CTkFrame(columns, fg_color=theme.PANEL, corner_radius=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = ctk.CTkFrame(columns, fg_color=theme.PANEL, corner_radius=14)
        right.grid(row=0, column=1, sticky="nsew")
        left_inner = ctk.CTkFrame(left, fg_color="transparent")
        left_inner.pack(fill="both", expand=True, padx=20, pady=20)
        right_inner = ctk.CTkFrame(right, fg_color="transparent")
        right_inner.pack(fill="both", expand=True, padx=20, pady=20)
        theme.text(left_inner, "01  АККАУНТ И РОЛИК", muted=True, font=("Segoe UI", 11, "bold"))
        self.mode = theme.field(left_inner, "Способ отправки", next(iter(MODES)), list(MODES))
        self.account = theme.field(left_inner, "Аккаунт TikTok", "Не подключён", ["Не подключён"])
        self.account_box = left_inner.winfo_children()[-1].winfo_children()[-1]
        row = ctk.CTkFrame(left_inner, fg_color="transparent")
        row.pack(fill="x")
        theme.button(row, "Подключить", self.connect, True)
        theme.button(row, "Отключить", self.disconnect)
        self.clip = theme.field(left_inner, "Ролик из библиотеки", "Выберите ролик", ["Выберите ролик"])
        self.clip_box = left_inner.winfo_children()[-1].winfo_children()[-1]
        row = ctk.CTkFrame(left_inner, fg_color="transparent")
        row.pack(fill="x")
        theme.button(row, "Смотреть ролик", self.preview)
        self.creator_label = theme.text(left_inner, "", muted=True, wraplength=370)
        theme.text(
            left_inner,
            "Для подключения нужны ключи приложения TikTok.\nНастройка: раздел «Настройки» → «TikTok».",
            muted=True,
            wraplength=370,
        )
        theme.text(right_inner, "02  НАСТРОЙКИ ПОСТА", muted=True, font=("Segoe UI", 11, "bold"))
        self.inbox_note = theme.text(
            right_inner,
            "В режиме черновика видео придёт во входящие TikTok.\nОткройте уведомление, добавьте описание и завершите\nпубликацию в TikTok самостоятельно.",
            muted=True,
            wraplength=390,
        )
        self.direct = ctk.CTkFrame(right_inner, fg_color="transparent")
        self.caption = theme.field(self.direct, "Описание и #хэштеги", "")
        self.privacy = theme.field(
            self.direct, "Кто увидит видео", "Выберите видимость", ["Выберите видимость"]
        )
        self.privacy_box = self.direct.winfo_children()[-1].winfo_children()[-1]
        self.options, self.switches = {}, {}
        for key, label in [
            ("allow_comment", "Разрешить комментарии"),
            ("allow_duet", "Разрешить дуэты"),
            ("allow_stitch", "Разрешить Stitch"),
            ("commercial", "Видео продвигает бренд / товар"),
            ("brand_organic", "Свой бренд · Promotional content"),
            ("brand_content", "Другой бренд · Paid partnership"),
            ("synthetic", "Контент создан с помощью ИИ"),
        ]:
            variable = tk.BooleanVar(value=False)
            switch = ctk.CTkCheckBox(
                self.direct,
                text=label,
                variable=variable,
                fg_color=theme.RED,
                hover_color=theme.RED,
                text_color=theme.WHITE,
                font=("Segoe UI", 11),
                command=self.validate_form,
            )
            switch.pack(anchor="w", pady=5)
            self.options[key], self.switches[key] = variable, switch
        self.notice = theme.text(right_inner, "", muted=True, wraplength=390)
        self.consent = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            right_inner,
            text="Подтверждаю отправку и условия TikTok",
            variable=self.consent,
            fg_color=theme.RED,
            hover_color=theme.RED,
            text_color=theme.WHITE,
            font=("Segoe UI", 11),
            command=self.validate_form,
        ).pack(anchor="w", pady=10)
        row = ctk.CTkFrame(right_inner, fg_color="transparent")
        row.pack(fill="x")
        self.submit = theme.button(row, "Отправить в TikTok", self.send, True)
        terms = ctk.CTkFrame(right_inner, fg_color="transparent")
        terms.pack(fill="x")
        for label, url in [
            ("Условия музыки", "https://www.tiktok.com/legal/page/global/music-usage-confirmation/en"),
            ("Правила рекламы", "https://www.tiktok.com/legal/page/global/bc-policy/en"),
        ]:
            ctk.CTkButton(
                terms,
                text=label,
                width=130,
                fg_color="transparent",
                text_color=theme.MUTED,
                command=lambda url=url: webbrowser.open(url),
            ).pack(side="left")
        self.tree = theme.table(
            self,
            [
                ("clip", "Ролик"),
                ("mode", "Способ"),
                ("status", "Статус"),
                ("progress", "Передано"),
                ("result", "Результат / ошибка"),
            ],
            5,
        )
        self.tree.column("result", width=330)
        row = self.toolbar()
        theme.button(row, "Проверить статус", self.check_status)
        theme.button(row, "Остановить передачу", self.cancel)
        theme.button(row, "Открыть TikTok", lambda: webbrowser.open("https://www.tiktok.com/"))
        theme.text(
            self,
            "После передачи файла обработка продолжается в TikTok. Отмена передачи не удаляет уже отправленный пост.",
            muted=True,
            wraplength=850,
        )
        self.mode.trace_add("write", lambda *_: self.mode_changed())
        self.account.trace_add("write", lambda *_: self.load_creator())
        self.privacy.trace_add("write", lambda *_: self.validate_form())
        self.clip.trace_add("write", lambda *_: self.clip_changed())
        self.mode_changed()

    def refresh(self, quiet=False):
        self.call("GET", "/tiktok/accounts", callback=self.accounts_loaded, quiet=quiet)
        self.call("GET", "/clips", callback=self.clips_loaded, quiet=quiet)
        self.call("GET", "/tiktok/jobs", callback=self.jobs_loaded, quiet=quiet)

    def accounts_loaded(self, rows):
        self.account_ids = {f"{r['name']} · {r['id'][:6]}": r["id"] for r in rows}
        choices = list(self.account_ids) or ["Не подключён"]
        self.account_box.configure(values=choices)
        if self.account.get() not in choices:
            self.account.set(choices[0])

    def clips_loaded(self, rows):
        self.clip_ids = {f"{r['title'][:40]} · {r['id'][:6]}": r for r in rows}
        self.clip_box.configure(values=list(self.clip_ids) or ["Выберите ролик"])
        self.validate_form()

    def jobs_loaded(self, rows):
        self.rows = {r["id"]: r for r in rows}
        theme.replace_rows(
            self.tree,
            [
                (
                    r["id"],
                    (
                        r["clip_id"][:8],
                        "Черновик" if r["mode"] == "inbox" else "Пост",
                        STATUSES.get(r["status"], r["status"]),
                        f"{r['progress']:.0f}%",
                        r["error"]
                        or (
                            "Завершите публикацию во входящих TikTok"
                            if r["status"] == "inbox"
                            else r["result"].get("status", "—")
                        ),
                    ),
                )
                for r in rows
            ],
        )

    def connect(self):
        self.call(
            "POST", "/tiktok/connect", {"mode": MODES[self.mode.get()]}, lambda r: webbrowser.open(r["url"])
        )

    def disconnect(self):
        identity = self.account_ids.get(self.account.get())
        if identity and messagebox.askyesno(
            "TikTok", "Отозвать доступ CLIP TRIBUNE к аккаунту?", parent=self
        ):
            self.call("DELETE", f"/tiktok/accounts/{identity}", callback=lambda _: self.refresh())

    def mode_changed(self):
        direct = MODES[self.mode.get()] == "direct"
        if direct:
            self.inbox_note.pack_forget()
            self.direct.pack(fill="x", before=self.notice)
        else:
            self.direct.pack_forget()
            self.inbox_note.pack(anchor="w", before=self.notice)
        self.consent.set(False)
        self.load_creator()

    def load_creator(self):
        self.creator_ready = False
        self.privacy.set("Выберите видимость")
        self.privacy_box.configure(values=["Выберите видимость"])
        identity = self.account_ids.get(self.account.get())
        for name in ("comment", "duet", "stitch"):
            self.options["allow_" + name].set(False)
            self.switches["allow_" + name].configure(state="disabled")
        self.creator_label.configure(
            text="Прямая публикация требует разрешения video.publish\nи соблюдения ограничений TikTok."
        )
        if identity and MODES[self.mode.get()] == "direct":

            def loaded(info):
                if identity != self.account_ids.get(self.account.get()) or MODES[self.mode.get()] != "direct":
                    return
                self.creator_ready = True
                self.creator_label.configure(
                    text=f"Автор: {info['creator_nickname']}\nЛимит длительности: {info['max_video_post_duration_sec']} сек."
                )
                self.privacy_box.configure(values=[PRIVACY.get(p, p) for p in info["privacy_level_options"]])
                for name in ("comment", "duet", "stitch"):
                    self.switches["allow_" + name].configure(
                        state="disabled" if info[name + "_disabled"] else "normal"
                    )
                self.validate_form()

            self.call("GET", f"/tiktok/accounts/{identity}/creator", callback=loaded)
        self.validate_form()

    def clip_changed(self):
        clip = self.clip_ids.get(self.clip.get())
        if clip:
            self.caption.set(clip["title"])
        self.consent.set(False)
        self.validate_form()

    def validate_form(self):
        direct = MODES[self.mode.get()] == "direct"
        ready = bool(
            self.consent.get() and self.account.get() in self.account_ids and self.clip.get() in self.clip_ids
        )
        notice = "Отправляя видео, вы принимаете Music Usage Confirmation TikTok."
        if direct:
            ready = ready and self.creator_ready and self.privacy.get() in PRIVACY.values()
            commercial = self.options["commercial"].get()
            for key in ("brand_organic", "brand_content"):
                self.switches[key].configure(state="normal" if commercial else "disabled")
                if not commercial:
                    self.options[key].set(False)
            if commercial and not (
                self.options["brand_organic"].get() or self.options["brand_content"].get()
            ):
                ready, notice = False, "Укажите, чей бренд продвигается: свой или другой."
            if self.options["brand_content"].get():
                notice = (
                    "Отправляя видео, вы принимаете Branded Content Policy и Music Usage Confirmation TikTok."
                )
                if self.privacy.get() == "Только я":
                    ready, notice = False, "Paid partnership: выберите видимость «Все» или «Друзья»."
        self.notice.configure(text=notice)
        self.submit.configure(state="normal" if ready else "disabled")

    def preview(self):
        clip = self.clip_ids.get(self.clip.get())
        if clip:
            self.call("GET", f"/clips/{clip['id']}/location", callback=lambda r: os.startfile(r["path"]))

    def send(self):
        clip = self.clip_ids.get(self.clip.get())
        if not clip or not self.consent.get():
            return
        data = dict(
            clip_id=clip["id"],
            account_id=self.account_ids[self.account.get()],
            mode=MODES[self.mode.get()],
            title=self.caption.get(),
            privacy_level=next((k for k, v in PRIVACY.items() if v == self.privacy.get()), ""),
            consent=True,
            **{k: v.get() for k, v in self.options.items()},
        )
        self.submit.configure(state="disabled")
        self.consent.set(False)
        self.call("POST", "/tiktok/jobs", data, lambda _: self.refresh())

    def check_status(self):
        for identity in self.selected(self.tree):
            self.call("POST", f"/tiktok/jobs/{identity}/status", callback=lambda _: self.refresh())

    def cancel(self):
        for identity in self.selected(self.tree):
            self.call("POST", f"/tiktok/jobs/{identity}/cancel", callback=lambda _: self.refresh())
