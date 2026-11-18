"""Внешние интеграции: метаданные трендов и управляемая публикация."""

import webbrowser
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk

from . import theme
from .base import Page, STATUSES, date


class TrendsPage(Page):
    title = "Тренды YouTube"
    subtitle = "Поиск тем через официальный API. Видео не скачиваются; Trend Score — наша расчётная оценка."

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.query = theme.field(self, "Тема поиска", "GTA VI")
        self.region = theme.field(self, "Регион", "US", ["AU", "NZ", "US", "GB", "CA", "DE", "FR", "JP"])
        self.hours = theme.field(self, "Период, часов", "24", ["1", "6", "24", "168"])
        theme.button(self.toolbar(), "Найти тренды", self.search, True)
        self.tree = theme.table(
            self,
            [
                ("title", "Видео"),
                ("channel", "Канал"),
                ("views", "Просмотры"),
                ("velocity", "Просмотров/ч"),
                ("score", "Trend Score"),
            ],
            8,
        )
        self.tree.column("title", width=350)
        self.tree.bind("<<TreeviewSelect>>", self.details)
        self.rows = {}
        self.info = theme.text(
            self,
            "Для поиска укажите YouTube API key в настройках. За последний час данных может быть мало.",
            muted=True,
            wraplength=850,
        )
        row = self.toolbar()
        theme.button(row, "Открыть оригинал", self.open_video)
        theme.button(row, "Использовать тему в студии", self.idea)

    def refresh(self, quiet=False):
        self.call("GET", "/trends", callback=self.loaded, quiet=quiet)

    def loaded(self, rows):
        self.rows = {row["id"]: row for row in rows}
        theme.replace_rows(
            self.tree,
            [
                (
                    r["id"],
                    (
                        r["data"]["title"],
                        r["data"]["channel"],
                        r["data"]["views"],
                        r["data"]["velocity"],
                        r["score"],
                    ),
                )
                for r in rows
            ],
        )

    def search(self):
        self.call(
            "POST",
            "/trends/search",
            dict(query=self.query.get(), region=self.region.get(), hours=int(self.hours.get())),
            self.loaded,
        )

    def details(self, _=None):
        selected = self.tree.selection()
        if selected:
            row = self.rows[selected[0]]
            data = row["data"]
            self.info.configure(
                text=f"Автор: {data['channel']} • Лайки: {data['likes'] or 'н/д'} • Комментарии: {data['comments'] or 'н/д'}\n"
                f"{data['idea']}\nПрава не получены. Для использования чужого материала свяжитесь с автором на странице канала."
            )

    def open_video(self):
        selected = self.selected(self.tree)
        if selected:
            webbrowser.open(self.rows[selected[0]]["data"]["url"])

    def idea(self):
        query = self.query.get()
        self.app.show_page("Студия")
        self.app.page.theme.set(query)


class PublisherPage(Page):
    title = "Публикация"
    subtitle = "Загрузка по умолчанию закрытая (private). Каждая ручная отправка требует вашего действия."

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.channel_ids = {}
        self.channel = theme.field(self, "YouTube-канал", "Не подключён", ["Не подключён"])
        # Сохраняем виджет combobox, чтобы обновлять список без перестройки формы.
        self.channel_box = self.winfo_children()[-1].winfo_children()[-1]
        row = self.toolbar()
        theme.button(row, "Подключить канал", self.connect, True)
        theme.button(row, "Отключить канал", self.disconnect)
        theme.button(
            row,
            "Остановить публикацию",
            lambda: self.call("POST", "/publishing/stop", callback=lambda _: self.refresh()),
        )
        self.quota = theme.text(self, "Получаем локальный счётчик квоты…", muted=True, wraplength=850)
        self.tree = theme.table(
            self,
            [
                ("clip", "Ролик"),
                ("status", "Статус"),
                ("progress", "Прогресс"),
                ("scheduled", "Не раньше"),
                ("error", "Ошибка / результат"),
            ],
            8,
        )
        self.tree.column("error", width=330)
        self.rows = {}
        row = self.toolbar()
        theme.button(row, "Отправить выбранные", self.send, True)
        theme.button(row, "Назначить время", self.schedule)
        theme.button(row, "Отменить", self.cancel)
        theme.button(row, "Открыть на YouTube", self.open_video)
        theme.button(self.toolbar(), "Проверить обработку YouTube", self.processing)
        theme.button(self.toolbar(), "Видимость и сведения о контенте", self.edit_options)
        theme.text(
            self,
            "Добавляйте ролики из «Библиотеки». Без подключённого канала очередь хранится локально.\nАвтоматическая отправка включается отдельно в настройках.",
            muted=True,
        )

    def refresh(self, quiet=False):
        self.call("GET", "/youtube/channels", callback=self.loaded_channels, quiet=quiet)
        self.call("GET", "/publisher", callback=self.loaded, quiet=quiet)

    def loaded_channels(self, rows):
        self.channel_ids = {f"{r['name']} · {r['youtube_id'][-6:]}": r["id"] for r in rows}
        choices = list(self.channel_ids) or ["Не подключён"]
        self.channel_box.configure(values=choices)
        if self.channel.get() not in choices:
            self.channel.set(choices[0])

    def loaded(self, result):
        self.rows = {r["id"]: r for r in result["jobs"]}
        theme.replace_rows(
            self.tree,
            [
                (
                    r["id"],
                    (
                        r["clip_id"][:8],
                        STATUSES[r["status"]],
                        f"{r['progress']:.0f}%",
                        date(r["scheduled_at"]),
                        r["error"] or (("YouTube: " + r["video_id"]) if r["video_id"] else "—"),
                    ),
                )
                for r in result["jobs"]
            ],
        )
        quota = result["quota"]["buckets"]
        self.quota.configure(
            text=f"Загрузки: {quota['upload']['used']}/{quota['upload']['limit']} • Поиск: {quota['search']['used']}/{quota['search']['limit']} • Остальные: {quota['general']['used']}/{quota['general']['limit']}\n"
            + result["quota"]["note"]
            + f" Отправка: {'включена' if result['enabled'] else 'остановлена'}."
        )

    def connect(self):
        self.call("POST", "/youtube/connect", callback=lambda result: webbrowser.open(result["url"]))

    def disconnect(self):
        identity = self.channel_ids.get(self.channel.get())
        if identity and messagebox.askyesno(
            "Отключить канал", "Отозвать доступ CLIP TRIBUNE к этому каналу?", parent=self
        ):
            self.call("DELETE", "/youtube/channels/" + identity, callback=lambda _: self.refresh())

    def send(self):
        selected = self.selected(self.tree)
        channel = self.channel_ids.get(self.channel.get())
        if not channel:
            messagebox.showinfo("YouTube", "Сначала подключите канал.", parent=self)
            return
        if selected and messagebox.askyesno(
            "Загрузка на YouTube",
            f"Отправить {len(selected)} ролик(а) на канал {self.channel.get()}?\nЗапланированное время будет сохранено.",
            parent=self,
        ):
            for identity in selected:
                self.call(
                    "POST", f"/publisher/{identity}/send", dict(channel_id=channel), lambda _: self.refresh()
                )

    def schedule(self):
        selected = self.selected(self.tree)
        if not selected:
            return
        value = simpledialog.askstring(
            "Расписание", "Местное время компьютера: ГГГГ-ММ-ДД ЧЧ:ММ", parent=self
        )
        if value:
            try:
                timestamp = datetime.strptime(value, "%Y-%m-%d %H:%M").timestamp()
                if timestamp <= datetime.now().timestamp():
                    raise ValueError()
            except ValueError:
                messagebox.showerror(
                    "Расписание", "Введите будущее время в формате 2026-11-20 18:30.", parent=self
                )
                return
            for identity in selected:
                self.call(
                    "PATCH", f"/publisher/{identity}", dict(scheduled_at=timestamp), lambda _: self.refresh()
                )

    def cancel(self):
        for identity in self.selected(self.tree):
            self.call("POST", f"/publisher/{identity}/cancel", {}, lambda _: self.refresh())

    def open_video(self):
        selected = self.selected(self.tree)
        if selected and self.rows[selected[0]]["video_id"]:
            webbrowser.open("https://www.youtube.com/watch?v=" + self.rows[selected[0]]["video_id"])

    def processing(self):
        selected = self.selected(self.tree)
        if selected:
            self.call(
                "GET",
                f"/publisher/{selected[0]}/processing",
                callback=lambda data: messagebox.showinfo("YouTube", str(data), parent=self),
            )

    def edit_options(self):
        selected = self.selected(self.tree)
        if not selected:
            return
        dialog = tk.Toplevel(self)
        dialog.title("Настройки загрузки")
        dialog.configure(bg=theme.BLACK)
        dialog.geometry("620x290")
        panel = ttk.Frame(dialog, padding=20)
        panel.pack(fill="both", expand=True)
        privacy = theme.field(panel, "Видимость", "private", ["private", "unlisted", "public"])
        synthetic, kids = tk.BooleanVar(), tk.BooleanVar()
        ttk.Checkbutton(panel, text="Содержит реалистичные синтетические материалы", variable=synthetic).pack(
            anchor="w", pady=8
        )
        ttk.Checkbutton(panel, text="Предназначено для детей", variable=kids).pack(anchor="w", pady=8)

        def save():
            data = dict(privacy=privacy.get(), synthetic=synthetic.get(), made_for_kids=kids.get())
            for identity in selected:
                self.call("PATCH", f"/publisher/{identity}", data, lambda _: self.refresh())
            dialog.destroy()

        ttk.Button(panel, text="Применить к выбранным", command=save, style="Accent.TButton").pack(
            anchor="w", pady=12
        )
