"""Выделение вебки мышью. Вся работа с Tk и изображениями идёт в UI-потоке."""

import base64
import io
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from PIL import Image, ImageOps, ImageTk

from . import theme

FITS = {"Заполнить с обрезкой": "crop", "Вписать целиком": "fit"}


def selection_region(start, end):
    """Движение мыши в любую сторону даёт прямоугольник внутри кадра."""
    x0, y0 = (max(0, min(1, n)) for n in start)
    x1, y1 = (max(0, min(1, n)) for n in end)
    width, height = abs(x1 - x0), abs(y1 - y0)
    if min(width, height) < 0.02:
        return None
    return dict(x=min(x0, x1), y=min(y0, y1), width=width, height=height)


def composition_preview(image, region, main_fit="crop", webcam_fit="crop"):
    """Тот же порядок половин, что в FFmpeg; реклама и субтитры здесь не рисуются."""

    def fit(source, mode):
        if mode == "crop":
            return ImageOps.fit(source, (252, 224), method=Image.Resampling.LANCZOS)
        return ImageOps.pad(source, (252, 224), method=Image.Resampling.LANCZOS, color=theme.BLACK)

    width, height = image.size
    # Чётные координаты совпадают с округлением crop-фильтра для yuv420p.
    w = max(2, int(width * region["width"] / 2) * 2)
    h = max(2, int(height * region["height"] / 2) * 2)
    x = min(width - w, int(width * region["x"] / 2) * 2)
    y = min(height - h, int(height * region["y"] / 2) * 2)
    result = Image.new("RGB", (252, 448), theme.BLACK)
    result.paste(fit(image, main_fit), (0, 0))
    result.paste(fit(image.crop((x, y, x + w, y + h)), webcam_fit), (0, 224))
    return result


class WebcamEditor(ctk.CTkToplevel):
    def __init__(self, parent, image, config, on_save):
        super().__init__(parent)
        self.title("CLIP TRIBUNE · Область вебки")
        self.geometry(
            f"{min(1120, self.winfo_screenwidth() - 80)}x{min(740, self.winfo_screenheight() - 100)}"
        )
        self.minsize(820, 560)
        self.configure(fg_color=theme.BLACK)
        self.image = image.convert("RGB")
        self.region = config.get("webcam_region")
        self.on_save = on_save
        self.anchor = None
        self.image_box = (0, 0, 1, 1)
        self.source_photo = self.result_photo = None
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=20)
        theme.text(body, "Вебка — в нижней половине", font=("Segoe UI", 23, "bold"))
        theme.text(body, "Обведите камеру стримера мышкой. Справа — будущий кадр 9:16.", muted=True)
        panes = ctk.CTkFrame(body, fg_color="transparent")
        panes.pack(fill="both", expand=True, pady=14)
        panes.columnconfigure(0, weight=3)
        panes.columnconfigure(1, weight=1)
        panes.rowconfigure(1, weight=1)
        ctk.CTkLabel(panes, text="ИСХОДНЫЙ КАДР", text_color=theme.MUTED).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(panes, text="ВЕРХ · ВИДЕО / НИЗ · ВЕБКА", text_color=theme.MUTED).grid(row=0, column=1)
        self.canvas = tk.Canvas(
            panes, width=640, height=360, bg=theme.PANEL, highlightthickness=0, cursor="crosshair"
        )
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=(0, 20))
        self.preview = tk.Canvas(panes, width=252, height=448, bg=theme.PANEL, highlightthickness=0)
        self.preview.grid(row=1, column=1, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _: self.draw())
        self.preview.bind("<Configure>", lambda _: self.draw_result())
        self.canvas.bind("<ButtonPress-1>", self.begin)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.finish)
        controls = ctk.CTkFrame(body, fg_color="transparent")
        controls.pack(fill="x")
        self.main_fit = theme.field(
            controls, "Основное видео", self.fit_label(config.get("main_fit", "crop")), list(FITS)
        )
        self.webcam_fit = theme.field(
            controls, "Вебка", self.fit_label(config.get("webcam_fit", "crop")), list(FITS)
        )
        self.main_fit.trace_add("write", lambda *_: self.draw_result())
        self.webcam_fit.trace_add("write", lambda *_: self.draw_result())
        self.notice = theme.text(
            body,
            "Кадр без рекламы и субтитров. Звук берётся из исходного стрима один раз.",
            muted=True,
            wraplength=900,
        )
        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x", pady=(12, 0))
        self.save_button = theme.button(actions, "Применить область", self.save, True)
        theme.button(actions, "Отмена", self.destroy)
        self.transient(parent.winfo_toplevel())
        self.bind("<Escape>", lambda _: self.destroy())
        self.draw_timer = self.after(80, self.draw)

    @staticmethod
    def fit_label(value):
        return next(label for label, code in FITS.items() if code == value)

    def draw(self):
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        display = ImageOps.contain(self.image, (width, height), Image.Resampling.LANCZOS)
        x, y = (width - display.width) / 2, (height - display.height) / 2
        self.image_box = (x, y, display.width, display.height)
        self.source_photo = ImageTk.PhotoImage(display, master=self)
        self.canvas.delete("all")
        self.canvas.create_image(x, y, image=self.source_photo, anchor="nw")
        self.draw_selection()

    def point(self, event):
        x, y, width, height = self.image_box
        return (event.x - x) / width, (event.y - y) / height

    def begin(self, event):
        point = self.point(event)
        self.anchor = point if all(0 <= n <= 1 for n in point) else None

    def drag(self, event):
        if self.anchor is not None:
            self.region = selection_region(self.anchor, self.point(event))
            self.draw_selection()

    def finish(self, event):
        self.drag(event)
        self.anchor = None

    def draw_selection(self):
        self.canvas.delete("selection")
        if self.region:
            x, y, width, height = self.image_box
            r = self.region
            self.canvas.create_rectangle(
                x + r["x"] * width,
                y + r["y"] * height,
                x + (r["x"] + r["width"]) * width,
                y + (r["y"] + r["height"]) * height,
                outline=theme.RED,
                width=3,
                tags="selection",
            )
        self.draw_result()

    def draw_result(self):
        if not hasattr(self, "save_button"):
            return
        self.preview.delete("all")
        self.save_button.configure(state="normal" if self.region else "disabled")
        if not self.region:
            self.preview.create_text(
                self.preview.winfo_width() / 2,
                self.preview.winfo_height() / 2,
                text="Выделите вебку\nна исходном кадре",
                fill=theme.MUTED,
                justify="center",
            )
            return
        result = composition_preview(
            self.image, self.region, FITS[self.main_fit.get()], FITS[self.webcam_fit.get()]
        )
        result = ImageOps.contain(
            result,
            (max(1, self.preview.winfo_width()), max(1, self.preview.winfo_height())),
            Image.Resampling.LANCZOS,
        )
        self.result_photo = ImageTk.PhotoImage(result, master=self)
        self.preview.create_image(
            self.preview.winfo_width() / 2, self.preview.winfo_height() / 2, image=self.result_photo
        )

    def save(self):
        if self.region:
            self.on_save(
                dict(
                    webcam_region=dict(self.region),
                    main_fit=FITS[self.main_fit.get()],
                    webcam_fit=FITS[self.webcam_fit.get()],
                )
            )
            self.destroy()

    def destroy(self):
        if getattr(self, "draw_timer", None):
            self.after_cancel(self.draw_timer)
        # ImageTk и StringVar освобождаем до ухода из главного потока.
        for name in ("main_fit", "webcam_fit"):
            variable = getattr(self, name, None)
            if variable:
                for modes, callback in variable.trace_info():
                    variable.trace_remove(modes, callback)
                setattr(self, name, None)
        super().destroy()
        self.source_photo = self.result_photo = None


class WebcamPanel(ctk.CTkFrame):
    """Одна панель для записи эфира и готового исходника в студии."""

    def __init__(self, parent, page, source):
        super().__init__(parent, fg_color="transparent")
        self.page, self.source = page, source
        self.config_data, self.source_key = {}, None
        self.editor = None
        self.second = theme.field(self, "Кадр / пропуск начала, сек.", "0", stacked=True)
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", pady=5)
        theme.button(controls, "Выделить вебку на кадре", self.load, True)
        self.status = theme.text(
            self,
            "Верх — видео, низ — вебка. Если Twitch показывает рекламу, задайте пропуск начала эфира: 0–120 секунд.",
            muted=True,
            wraplength=420,
            font=("Segoe UI", 11),
        )

    def load(self):
        try:
            data = self.source()
            data["second"] = float(self.second.get().replace(",", "."))
        except ValueError as error:
            messagebox.showerror("Вебка", str(error), parent=self)
            return
        key = data.get("asset_id") or data.get("url")
        self.status.configure(text="Получаем кадр… Ждём указанный пропуск начала и загрузку изображения.")

        def loaded(result):
            if not self.winfo_exists():
                return
            self.status.configure(text="Обведите камеру и нажмите «Применить область».")
            picture = Image.open(io.BytesIO(base64.b64decode(result["png"]))).convert("RGB")
            if self.editor and self.editor.winfo_exists():
                self.editor.destroy()
            self.editor = WebcamEditor(
                self,
                picture,
                self.config_data if key == self.source_key else {},
                lambda config: self.saved(key, config),
            )

        self.page.call("POST", "/webcam/frame", data, loaded)

    def saved(self, key, config):
        self.source_key, self.config_data = key, config
        self.status.configure(text="Область вебки сохранена. Экспорт: 50% основное видео / 50% вебка.")

    def options(self):
        data = self.source()
        if not self.config_data or self.source_key != (data.get("asset_id") or data.get("url")):
            raise ValueError("Выделите вебку на кадре выбранного исходника или эфира")
        return {"layout": "webcam", **self.config_data}

    def destroy(self):
        if self.editor and self.editor.winfo_exists():
            self.editor.destroy()
        super().destroy()
        self.second = None
