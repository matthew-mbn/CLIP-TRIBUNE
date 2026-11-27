"""Понятная форма рекламы: материал → время → размещение → проверка."""

import base64
import io
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from . import theme
from .base import Page

MODES = {"Один раз за ролик": "once", "Баннер на весь ролик": "banner"}
POSITIONS = {
    "Сверху слева": "top_left",
    "Сверху по центру": "top",
    "Сверху справа": "top_right",
    "Слева": "left",
    "По центру": "center",
    "Справа": "right",
    "Снизу слева": "bottom_left",
    "Снизу по центру": "bottom",
    "Снизу справа": "bottom_right",
}


def card(parent):
    panel = ctk.CTkFrame(
        parent, fg_color=theme.PANEL, corner_radius=12, border_width=1, border_color=theme.LINE
    )
    panel.pack(fill="x", pady=(0, 16))
    body = ctk.CTkFrame(panel, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=20, pady=18)
    return body


class AdsPage(Page):
    title = "Реклама"
    subtitle = "Вставка с удалением зелёного фона. Разовая реклама может ставить основное видео на паузу."

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.assets = {}
        self.clips = {}
        self.initialized = False
        self.preselected = None
        self.preview_image = None
        layout = ctk.CTkFrame(self, fg_color="transparent")
        layout.pack(fill="x", pady=(18, 0))
        layout.columnconfigure(0, weight=3, uniform="ads")
        layout.columnconfigure(1, weight=2, uniform="ads")
        left = ctk.CTkFrame(layout, fg_color="transparent")
        left.grid(row=0, column=0, sticky="new", padx=(0, 20))
        right = ctk.CTkFrame(layout, fg_color="transparent")
        right.grid(row=0, column=1, sticky="new")
        material = card(left)
        theme.text(material, "01  /  Рекламный материал", font=("Segoe UI", 16, "bold"))
        self.asset = theme.field(
            material, "Видео или изображение", "Выберите вставку", ["Выберите вставку"], stacked=True
        )
        self.asset_widget = material.winfo_children()[-1].winfo_children()[-1]
        theme.button(material, "+ Загрузить вставку", self.import_file)
        timing = card(left)
        theme.text(timing, "02  /  Когда показывать", font=("Segoe UI", 16, "bold"))
        self.mode = theme.field(timing, "Режим", next(iter(MODES)), list(MODES), stacked=True)
        self.start = theme.field(timing, "Начало, сек. от начала ролика", "3", stacked=True)
        self.duration = theme.field(timing, "Длительность, сек. · 0 = длина вставки", "0", stacked=True)
        self.timing_widgets = [row.winfo_children()[-1] for row in timing.winfo_children()[-2:]]
        self.mode.trace_add("write", lambda *_: self.timing_changed())
        theme.text(
            timing,
            "Баннер повторяется до конца. Изображение с длительностью 0 показывается 5 секунд.",
            muted=True,
            wraplength=400,
            font=("Segoe UI", 11),
        )
        self.pause = tk.BooleanVar(value=True)
        self.sound = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            timing, text="Пауза видео и звука на время разовой рекламы", variable=self.pause
        ).pack(anchor="w", pady=6)
        ctk.CTkCheckBox(timing, text="Звук рекламной вставки", variable=self.sound).pack(anchor="w", pady=6)
        placement = card(left)
        theme.text(placement, "03  /  Размещение и фон", font=("Segoe UI", 16, "bold"))
        self.position = theme.field(placement, "Положение", "Снизу по центру", list(POSITIONS), stacked=True)
        self.width = theme.field(placement, "Ширина, % от кадра", "70", stacked=True)
        self.margin = theme.field(placement, "Отступ, %", "3", stacked=True)
        self.color = theme.field(placement, "Цвет фона · HEX", "#00FF00", stacked=True)
        self.similarity = theme.field(placement, "Удаление фона · 0.01–0.80", "0.22", stacked=True)
        self.blend = theme.field(placement, "Мягкость края · 0–0.50", "0.08", stacked=True)
        theme.text(
            placement,
            "Остался зелёный фон? Увеличьте удаление фона.\nИсчезают детали? Уменьшите его.",
            muted=True,
            wraplength=400,
            font=("Segoe UI", 11),
        )
        saved = card(left)
        self.enabled = tk.BooleanVar(value=False)
        ctk.CTkSwitch(
            saved,
            text="Добавлять в новые нарезки",
            variable=self.enabled,
            progress_color=theme.RED,
            font=("Segoe UI", 12),
        ).pack(anchor="w", pady=(0, 12))
        theme.button(saved, "Сохранить настройки", self.save, True)
        preview = card(right)
        theme.text(preview, "ПРЕДПРОСМОТР", muted=True, font=("Segoe UI", 11, "bold"))
        self.preview = ctk.CTkLabel(
            preview,
            text="Загрузите вставку\nи обновите предпросмотр",
            height=360,
            fg_color=theme.BLACK,
            corner_radius=12,
            text_color=theme.MUTED,
            font=("Segoe UI", 13),
        )
        self.preview.pack(fill="x", pady=(0, 12))
        theme.button(preview, "Обновить предпросмотр", self.show_preview)
        theme.text(
            right,
            "Проверка фона и положения на кадре 0,5 сек. вставки.\nЗвук включается отдельной настройкой.",
            muted=True,
            wraplength=340,
            font=("Segoe UI", 11),
        )
        existing = card(right)
        theme.text(existing, "Готовый ролик", font=("Segoe UI", 16, "bold"))
        self.clip = theme.field(
            existing, "Фон для проверки / ролик для копии", "Тестовый фон", ["Тестовый фон"], stacked=True
        )
        self.clip_widget = existing.winfo_children()[-1].winfo_children()[-1]
        theme.text(
            existing,
            "Можно добавить рекламу к ролику из библиотеки. Будет создана отдельная копия.",
            muted=True,
            wraplength=310,
            font=("Segoe UI", 12),
        )
        theme.button(existing, "Создать копию с рекламой", self.apply, True)
        self.notice = theme.text(self, "", muted=True, wraplength=950)

    def timing_changed(self):
        for widget in self.timing_widgets:
            widget.configure(state="disabled" if MODES[self.mode.get()] == "banner" else "normal")

    def refresh(self, quiet=False):
        # Автоопрос не должен перезаписывать несохранённый ввод пользователя.
        if not quiet:
            self.call("GET", "/ads", callback=self.loaded)
            self.call("GET", "/clips", callback=self.clips_loaded)

    def loaded(self, result):
        self.assets = {f"{a['name']} · {a['id'][:6]}": a["id"] for a in result["assets"]}
        self.asset_widget.configure(values=list(self.assets) or ["Выберите вставку"])
        if self.initialized:
            return
        self.initialized = True
        config = result["config"]
        self.asset.set(
            next(
                (label for label, identity in self.assets.items() if identity == config["asset_id"]),
                "Выберите вставку",
            )
        )
        self.enabled.set(config["enabled"])
        self.pause.set(config.get("pause_video", True))
        self.sound.set(config.get("sound", True))
        self.mode.set(next(label for label, value in MODES.items() if value == config["mode"]))
        self.position.set(next(label for label, value in POSITIONS.items() if value == config["position"]))
        for variable, key in [
            (self.start, "start"),
            (self.duration, "duration"),
            (self.width, "width_percent"),
            (self.margin, "margin_percent"),
            (self.color, "key_color"),
            (self.similarity, "similarity"),
            (self.blend, "blend"),
        ]:
            variable.set(str(config[key]))
        self.timing_changed()

    def clips_loaded(self, clips):
        self.clips = {f"{clip['title'][:40]} · {clip['id'][:6]}": clip["id"] for clip in clips}
        self.clip_widget.configure(values=["Тестовый фон", *self.clips])
        if self.preselected:
            self.clip.set(
                next(
                    (label for label, identity in self.clips.items() if identity == self.preselected),
                    "Тестовый фон",
                )
            )
            self.preselected = None

    def import_file(self):
        path = filedialog.askopenfilename(
            parent=self, filetypes=[("Вставки", "*.mp4 *.mov *.mkv *.webm *.png *.jpg *.jpeg *.webp")]
        )
        if path:
            self.call("POST", "/ads/import", {"path": path}, self.imported)

    def imported(self, asset):
        label = f"{asset['name']} · {asset['id'][:6]}"
        self.assets[label] = asset["id"]
        self.asset_widget.configure(values=list(self.assets))
        self.asset.set(label)
        self.notice.configure(text="Вставка скопирована в хранилище. Настройте показ и сохраните настройки.")

    def config(self):
        try:
            return dict(
                enabled=self.enabled.get(),
                pause_video=self.pause.get(),
                sound=self.sound.get(),
                asset_id=self.assets.get(self.asset.get(), ""),
                mode=MODES[self.mode.get()],
                start=float(self.start.get().replace(",", ".")),
                duration=float(self.duration.get().replace(",", ".")),
                position=POSITIONS[self.position.get()],
                width_percent=int(self.width.get()),
                margin_percent=int(self.margin.get()),
                key_color=self.color.get().strip(),
                similarity=float(self.similarity.get().replace(",", ".")),
                blend=float(self.blend.get().replace(",", ".")),
            )
        except ValueError:
            messagebox.showerror("Реклама", "Проверьте числа в параметрах рекламы.", parent=self)
            return None

    def save(self):
        if (config := self.config()) is not None:
            self.call(
                "PUT",
                "/ads",
                config,
                lambda _: self.notice.configure(text="Сохранено. Новые задания используют эти настройки."),
            )

    def show_preview(self):
        if (config := self.config()) is not None:
            self.call(
                "POST",
                "/ads/preview",
                dict(config=config, clip_id=self.clips.get(self.clip.get())),
                self.preview_loaded,
            )

    def preview_loaded(self, result):
        with Image.open(io.BytesIO(base64.b64decode(result["png"]))) as picture:
            scale = min(280 / picture.width, 360 / picture.height)
            size = (max(1, round(picture.width * scale)), max(1, round(picture.height * scale)))
            self.preview_image = ctk.CTkImage(picture.copy(), size=size)
        self.preview.configure(image=self.preview_image, text="")

    def apply(self):
        if self.clip.get() not in self.clips:
            messagebox.showinfo("Реклама", "Выберите готовый ролик для создания копии.", parent=self)
            return
        if (config := self.config()) is not None:
            self.call(
                "POST",
                "/ads/apply",
                dict(config=config, clip_id=self.clips[self.clip.get()]),
                lambda _: self.call(
                    "POST", "/control/resume-queue", callback=lambda _: self.app.show_page("Очередь")
                ),
            )
