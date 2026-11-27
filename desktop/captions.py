"""Редактор фраз: список таймингов, оформление и настоящий кадр предпросмотра."""

import base64
import io
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from PIL import Image
from . import theme

STYLES = {
    "Классический": "classic",
    "Крупный с обводкой": "bold",
    "На подложке": "box",
    "Красный акцент": "red",
}


class CaptionEditor(ctk.CTkToplevel):
    def __init__(self, parent, app, identity):
        super().__init__(parent)
        self.app, self.identity, self.cues = app, identity, []
        self.timer = None
        self.photo = None
        self.title("CLIP TRIBUNE · Субтитры")
        width = min(1100, self.winfo_screenwidth() - 60)
        height = min(820, self.winfo_screenheight() - 80)
        self.geometry(f"{width}x{height}+{max(0, (self.winfo_screenwidth() - width) // 2)}+30")
        self.configure(fg_color=theme.BLACK)
        body = ctk.CTkScrollableFrame(self, fg_color=theme.BLACK)
        body.pack(fill="both", expand=True, padx=18, pady=18)
        theme.text(body, "Субтитры", font=("Segoe UI", 26, "bold"))
        theme.text(
            body,
            "Распознайте речь, исправьте фразы и задайте время показа. Исходный ролик сохраняется.",
            muted=True,
        )
        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x", pady=12)
        theme.button(actions, "Скачать модель · 148 МБ", self.install)
        theme.button(actions, "Распознать речь", self.recognize, True)
        theme.button(actions, "Загрузить сохранённые фразы", self.load)
        self.notice = theme.text(body, "", muted=True, wraplength=950)
        panes = ctk.CTkFrame(body, fg_color="transparent")
        panes.pack(fill="both", expand=True)
        left = ctk.CTkFrame(panes, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=(0, 20))
        right = ctk.CTkFrame(panes, fg_color="transparent")
        right.pack(side="right", fill="y")
        self.tree = theme.table(
            left, [("start", "Начало"), ("end", "Конец"), ("text", "Фраза"), ("on", "Показ")], 4
        )
        self.tree.column("text", width=280)
        self.tree.bind("<<TreeviewSelect>>", self.selected)
        self.start = theme.field(left, "Начало, сек.", "0")
        self.end = theme.field(left, "Конец, сек.", "2")
        self.text = theme.field(left, "Текст", "")
        self.enabled = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(left, text="Показывать эту фразу", variable=self.enabled).pack(anchor="w", pady=8)
        buttons = ctk.CTkFrame(left, fg_color="transparent")
        buttons.pack(fill="x")
        theme.button(buttons, "Применить к фразе", self.apply)
        theme.button(buttons, "+ Фраза", self.add)
        theme.button(buttons, "Удалить фразу", self.remove)
        self.style = theme.field(left, "Стиль", "Крупный с обводкой", list(STYLES))
        self.second = theme.field(left, "Кадр предпросмотра, сек.", "0")
        theme.button(left, "Обновить предпросмотр", self.preview)
        theme.button(left, "Создать копию с субтитрами", self.render, True)
        self.image = ctk.CTkLabel(
            right, text="Предпросмотр\nс выбранным оформлением", width=300, height=534, fg_color=theme.PANEL
        )
        self.image.pack(pady=10)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.load()

    def call(self, method, path, data=None, callback=None):
        def delivered(result):
            if self.winfo_exists() and callback:
                callback(result)

        self.app.async_call(method, path, data, delivered)

    def load(self):
        def loaded(data):
            self.cues = data["cues"]
            self.style.set(next(k for k, v in STYLES.items() if v == data["style"]))
            text = (
                "Распознавание готово к работе."
                if data["speech_ready"]
                else "Сначала скачайте модель: один раз, затем работает без интернета."
            )
            if data["legacy_burned"]:
                text += " В старом ролике буквы уже вшиты: для их замены заново создайте клип из исходника."
            self.notice.configure(text=text)
            self.draw()

        self.call("GET", f"/editing/captions/{self.identity}", callback=loaded)

    def draw(self):
        theme.replace_rows(
            self.tree,
            [
                (
                    str(i),
                    (
                        f"{r['start']:.2f}",
                        f"{r['end']:.2f}",
                        r["text"],
                        "Да" if r.get("enabled", True) else "Нет",
                    ),
                )
                for i, r in enumerate(self.cues)
            ],
        )

    def selected(self, _=None):
        selected = self.tree.selection()
        if selected:
            row = self.cues[int(selected[0])]
            self.start.set(str(row["start"]))
            self.end.set(str(row["end"]))
            self.text.set(row["text"])
            self.enabled.set(row.get("enabled", True))
            self.second.set(str(row["start"]))

    def apply(self):
        selected = self.tree.selection()
        if not selected:
            return True
        try:
            from backend.captions import Cue

            row = Cue(
                start=float(self.start.get().replace(",", ".")),
                end=float(self.end.get().replace(",", ".")),
                text=self.text.get(),
                enabled=self.enabled.get(),
            ).model_dump()
        except ValueError:
            messagebox.showerror("Субтитры", "Проверьте время: конец должен быть позже начала.", parent=self)
            return False
        self.cues[int(selected[0])] = row
        self.draw()
        return True

    def add(self):
        self.cues.append(dict(start=0, end=2, text="Новая фраза", enabled=True))
        self.draw()
        self.tree.selection_set(str(len(self.cues) - 1))
        self.selected()

    def remove(self):
        selected = self.tree.selection()
        if selected:
            self.cues.pop(int(selected[0]))
            self.tree.selection_remove(*selected)
            self.draw()

    def data(self):
        return dict(style=STYLES[self.style.get()], cues=self.cues)

    def preview(self):
        if not self.apply():
            return
        try:
            data = {**self.data(), "second": float(self.second.get().replace(",", "."))}
        except ValueError:
            return

        def shown(result):
            image = Image.open(io.BytesIO(base64.b64decode(result["png"])))
            self.photo = ctk.CTkImage(image, size=(300, round(300 * image.height / image.width)))
            self.image.configure(image=self.photo, text="")

        self.call("POST", f"/editing/captions/{self.identity}/preview", data, shown)

    def job(self, result):
        identity = result["id"]
        self.notice.configure(text="Задание выполняется; можно отменить его в «Очереди».")

        def poll():
            def received(rows):
                item = next((r for r in rows if r["id"] == identity), None)
                if item and item["status"] in ("ready", "failed", "cancelled"):
                    self.notice.configure(text=item["error"] or item["message"])
                    if item["status"] == "ready" and item["kind"] in ("speech_setup", "caption_transcribe"):
                        self.load()
                else:
                    self.timer = self.after(1500, poll)

            self.call("GET", "/jobs", callback=received)

        poll()

    def install(self):
        self.call("POST", "/editing/speech/install", callback=self.job)

    def recognize(self):
        if self.cues and not messagebox.askyesno(
            "Субтитры", "Заново распознать речь и заменить сохранённые фразы?", parent=self
        ):
            return
        self.call("POST", f"/editing/captions/{self.identity}/recognize", callback=self.job)

    def render(self):
        if self.apply():
            self.call("POST", f"/editing/captions/{self.identity}/render", self.data(), self.job)

    def destroy(self):
        if self.timer:
            self.after_cancel(self.timer)
        super().destroy()
        self.start = self.end = self.text = self.style = self.second = self.enabled = self.photo = None
