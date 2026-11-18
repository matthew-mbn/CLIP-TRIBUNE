"""Обзор студии: компактные показатели, реальная история и последние клипы."""

import tkinter as tk
from datetime import datetime

import customtkinter as ctk
from PIL import Image, ImageOps

from . import theme
from .base import Page, date


class DashboardPage(Page):
    title = "Обзор студии"
    subtitle = "От длинного видео до следующей короткой истории. Всё под вашим контролем."

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.production = "stopped"
        self.history = []
        self.clip_signature = None
        self.images = []
        actions = self.toolbar()
        theme.button(actions, "+  Создать нарезки", lambda: app.show_page("Студия"), True)
        theme.button(actions, "Импортировать видео", lambda: app.show_page("Источники"))
        theme.button(actions, "Тестовая нарезка", self.demo)

        metrics = ctk.CTkFrame(self, fg_color="transparent")
        metrics.pack(fill="x", pady=(18, 20))
        self.values = {}
        for index, (key, label, hint, symbol) in enumerate(
            [
                ("sources", "Исходники", "В вашей медиатеке", "⊞"),
                ("today", "Создано сегодня", "Готовые видео за день", "✦"),
                ("queued", "В очереди", "Ожидают обработки", "≡"),
                ("ready", "Готово к публикации", "Проверьте и отправьте", "↗"),
            ]
        ):
            metrics.columnconfigure(index, weight=1, uniform="metric")
            card = ctk.CTkFrame(
                metrics, fg_color=theme.PANEL, corner_radius=12, border_width=1, border_color=theme.LINE
            )
            card.grid(
                row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 7, 0 if index == 3 else 7)
            )
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=20, pady=(16, 0))
            ctk.CTkLabel(top, text=label, text_color=theme.MUTED, font=("Segoe UI", 12)).pack(side="left")
            ctk.CTkLabel(top, text=symbol, text_color=theme.RED, font=("Segoe UI", 20)).pack(side="right")
            variable = tk.StringVar(value="—")
            self.values[key] = variable
            ctk.CTkLabel(
                card, textvariable=variable, text_color=theme.WHITE, font=("Segoe UI", 34, "bold"), height=44
            ).pack(anchor="w", padx=20)
            ctk.CTkLabel(card, text=hint, text_color="#727581", font=("Segoe UI", 11)).pack(
                anchor="w", padx=20, pady=(0, 14)
            )

        middle = ctk.CTkFrame(self, fg_color="transparent")
        middle.pack(fill="x", pady=(0, 22))
        middle.columnconfigure(0, weight=7)
        middle.columnconfigure(1, weight=3)
        chart_card = ctk.CTkFrame(
            middle, fg_color=theme.PANEL, corner_radius=12, border_color=theme.LINE, border_width=1
        )
        chart_card.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        heading = ctk.CTkFrame(chart_card, fg_color="transparent")
        heading.pack(fill="x", padx=22, pady=(16, 0))
        ctk.CTkLabel(
            heading, text="Выпуск роликов", font=("Segoe UI", 15, "bold"), text_color=theme.WHITE
        ).pack(side="left")
        ctk.CTkLabel(heading, text="Последние 12 часов", font=("Segoe UI", 11), text_color=theme.MUTED).pack(
            side="right"
        )
        self.chart = tk.Canvas(chart_card, height=150, bg=theme.PANEL, highlightthickness=0)
        self.chart.pack(fill="x", padx=22, pady=(8, 4))
        self.chart.bind("<Configure>", lambda _: self.draw_chart())
        self.chart_note = ctk.CTkLabel(
            chart_card,
            text="Показаны фактически созданные ролики",
            text_color="#737682",
            font=("Segoe UI", 11),
        )
        self.chart_note.pack(anchor="w", padx=22, pady=(0, 14))

        automation = ctk.CTkFrame(
            middle, fg_color=theme.PANEL, corner_radius=12, border_color=theme.LINE, border_width=1
        )
        automation.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(
            automation, text="Автопроизводство", font=("Segoe UI", 15, "bold"), text_color=theme.WHITE
        ).pack(anchor="w", padx=22, pady=(18, 8))
        self.mode = ctk.CTkLabel(
            automation,
            text="●  Выключено",
            font=("Segoe UI", 11),
            text_color=theme.MUTED,
            fg_color=theme.SURFACE,
            corner_radius=6,
            height=26,
            width=112,
        )
        self.mode.pack(anchor="w", padx=22)
        ctk.CTkLabel(
            automation,
            text="Новые исходники → анализ → монтаж.\nНастройте один раз и запускайте поток.",
            justify="left",
            text_color=theme.MUTED,
            font=("Segoe UI", 12),
        ).pack(anchor="w", padx=22, pady=12)
        self.auto_button = ctk.CTkButton(
            automation,
            text="Начать обработку",
            command=self.toggle_production,
            height=36,
            corner_radius=8,
            fg_color=theme.RED,
            hover_color="#d83444",
            font=("Segoe UI", 12, "bold"),
        )
        self.auto_button.pack(fill="x", padx=22, pady=(0, 10))
        self.worker = ctk.CTkLabel(
            automation, text="Проверяем движок…", text_color="#737682", font=("Segoe UI", 11)
        )
        self.worker.pack(anchor="w", padx=22, pady=(0, 12))

        heading = ctk.CTkFrame(self, fg_color="transparent")
        heading.pack(fill="x")
        ctk.CTkLabel(
            heading, text="Последние ролики", text_color=theme.WHITE, font=("Segoe UI", 17, "bold")
        ).pack(side="left")
        ctk.CTkButton(
            heading,
            text="Вся библиотека  ↗",
            width=140,
            height=30,
            corner_radius=6,
            fg_color="transparent",
            hover_color=theme.PANEL,
            text_color=theme.MUTED,
            font=("Segoe UI", 12),
            command=lambda: app.show_page("Библиотека"),
        ).pack(side="right")
        self.gallery = ctk.CTkFrame(self, fg_color="transparent")
        self.gallery.pack(fill="x", pady=(12, 18))
        self.summary = theme.text(self, "Загружаем активность…", muted=True)

    def refresh(self, quiet=False):
        self.call("GET", "/dashboard", callback=self.loaded, quiet=quiet)
        self.call("GET", "/clips", callback=self.load_clips, quiet=True)

    def loaded(self, data):
        for key, variable in self.values.items():
            variable.set(str(data[key]))
        self.production = data["production"]
        labels = {
            "running": ("●  В работе", "Приостановить"),
            "paused": ("●  Пауза", "Продолжить"),
            "stopped": ("●  Выключено", "Начать обработку"),
        }
        label, action = labels[self.production]
        self.mode.configure(text=label, text_color=theme.RED if self.production == "running" else theme.MUTED)
        self.auto_button.configure(text=action)
        worker = data["worker"]
        self.worker.configure(
            text=f"Движок {'на связи' if worker.get('alive') else 'недоступен'}  ·  {worker.get('free_gb', '—')} ГБ свободно"
        )
        self.summary.configure(
            text=f"Опубликовано: {data['published']}   ·   В обработке: {data['processing']}   ·   Ошибок: {data['errors']}   ·   Наблюдений трендов: {data['trends']}"
        )

    def draw_chart(self):
        canvas = self.chart
        canvas.delete("all")
        width = max(200, canvas.winfo_width())
        left, right, top, bottom = 24, width - 12, 12, 120
        counts = [0] * 12
        current_hour = int(datetime.now().timestamp() // 3600)
        for created in self.history:
            index = int(created // 3600) - current_hour + 11
            if 0 <= index < 12:
                counts[index] += 1
        peak = max(2, *counts)
        for ratio in (0, 0.5, 1):
            y = bottom - ratio * (bottom - top)
            canvas.create_line(left, y, right, y, fill=theme.LINE, dash=(2, 5))
            canvas.create_text(8, y, text=str(round(peak * ratio)), fill="#747783", font=("Segoe UI", 8))
        points = [
            (left + (right - left) * i / 11, bottom - value / peak * (bottom - top))
            for i, value in enumerate(counts)
        ]
        flattened = [coordinate for point in points for coordinate in point]
        canvas.create_polygon(left, bottom, *flattened, right, bottom, fill="#2a1a21", outline="")
        canvas.create_line(*flattened, fill=theme.RED, width=2, smooth=False)
        for x, y in points:
            canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=theme.RED, outline="")
        for index in (0, 3, 6, 9, 11):
            hour = datetime.fromtimestamp((current_hour - 11 + index) * 3600).strftime("%H:00")
            canvas.create_text(points[index][0], 143, text=hour, fill="#747783", font=("Segoe UI", 8))

    def load_clips(self, clips):
        self.history = [clip["created_at"] for clip in clips]
        self.draw_chart()
        signature = tuple((clip["id"], clip["status"]) for clip in clips[:3])
        if signature == self.clip_signature:
            return
        self.clip_signature = signature
        for child in self.gallery.winfo_children():
            child.destroy()
        self.images.clear()
        if not clips:
            empty = ctk.CTkFrame(self.gallery, fg_color=theme.PANEL, corner_radius=12)
            empty.pack(fill="x")
            ctk.CTkLabel(empty, text="Ваша первая история — впереди", font=("Segoe UI", 17, "bold")).pack(
                pady=(24, 4)
            )
            ctk.CTkLabel(
                empty,
                text="Добавьте исходник или создайте тестовую нарезку.",
                text_color=theme.MUTED,
                font=("Segoe UI", 12),
            ).pack(pady=(0, 24))
            return
        for index, clip in enumerate(clips[:3]):
            self.gallery.columnconfigure(index, weight=1, uniform="clip")
            card = ctk.CTkFrame(
                self.gallery, fg_color=theme.PANEL, corner_radius=12, border_width=1, border_color=theme.LINE
            )
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 7, 7))
            preview = ctk.CTkLabel(
                card,
                text="▶",
                height=118,
                corner_radius=8,
                fg_color=theme.SURFACE,
                text_color=theme.WHITE,
                font=("Segoe UI", 25),
            )
            preview.pack(fill="x", padx=10, pady=(10, 8))
            preview.bind("<Button-1>", lambda _, identity=clip["id"]: self.play(identity))
            title = clip["title"][:43] + ("…" if len(clip["title"]) > 43 else "")
            ctk.CTkLabel(
                card, text=title, anchor="w", text_color=theme.WHITE, font=("Segoe UI", 12, "bold")
            ).pack(fill="x", padx=14)
            ctk.CTkLabel(
                card,
                text=f"{round(clip['duration'])} сек.    ·    {date(clip['created_at'])}    ·    Готово",
                anchor="w",
                text_color=theme.MUTED,
                font=("Segoe UI", 10),
            ).pack(fill="x", padx=14, pady=(0, 12))
            self.call(
                "GET",
                f"/clips/{clip['id']}/location",
                callback=lambda result, target=preview: self.show_preview(target, result),
                quiet=True,
            )

    def show_preview(self, label, location):
        if not label.winfo_exists():
            return
        with Image.open(location["thumbnail"]) as original:
            picture = ImageOps.fit(original, (480, 236))
        image = ctk.CTkImage(light_image=picture, dark_image=picture, size=(240, 118))
        self.images.append(image)
        label.configure(image=image, text="")

    def play(self, identity):
        import os

        self.call("GET", f"/clips/{identity}/location", callback=lambda result: os.startfile(result["path"]))

    def toggle_production(self):
        action = (
            "pause" if self.production == "running" else "resume" if self.production == "paused" else "start"
        )
        self.call("POST", "/control/" + action, callback=lambda _: self.refresh())

    def demo(self):
        self.call("POST", "/demo", callback=lambda _: self.app.show_page("Очередь"))
