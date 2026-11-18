"""Общий каркас страницы и русские названия статусов."""

from datetime import datetime
import tkinter as tk
import customtkinter as ctk
from tkinter import messagebox, ttk

from . import theme

STATUSES = dict(
    pending="В очереди",
    analyzing="Анализ",
    rendering="Рендеринг",
    ready="Готово",
    publishing="Загрузка",
    published="Опубликовано",
    failed="Ошибка",
    cancelled="Отменено",
    processing="Обработка TikTok",
    inbox="Во входящих TikTok",
    interrupted="Нужна проверка",
)


def date(value):
    return datetime.fromtimestamp(value).strftime("%d.%m %H:%M") if value else "—"


class Page(ctk.CTkFrame):
    title = ""
    subtitle = ""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color=theme.BLACK, corner_radius=0)
        self.app = app
        theme.text(self, self.title, font=("Segoe UI", 26, "bold"))
        theme.text(self, self.subtitle, muted=True, wraplength=850)

    def call(self, method, path, data=None, callback=None, quiet=False):
        def delivered(result):
            if self.winfo_exists() and callback:
                callback(result)

        self.app.async_call(method, path, data, delivered, quiet)

    def refresh(self, quiet=False):
        pass

    def destroy(self):
        # CTk сначала снимает собственные trace callbacks у полей и переключателей.
        super().destroy()
        # Удаляем трассировки и переменные в UI-потоке. Иначе циклическая ссылка
        # Variable → callback → Page может быть собрана GC в HTTP-потоке.
        for key, value in list(vars(self).items()):
            if isinstance(value, (tk.Image, ctk.CTkImage)):
                # Tcl-изображения также нужно освобождать в потоке интерфейса.
                setattr(self, key, None)
            elif isinstance(value, tk.Variable):
                for modes, callback in value.trace_info():
                    value.trace_remove(modes, callback)
                setattr(self, key, None)
            elif (
                isinstance(value, dict)
                and value
                and all(isinstance(item, tk.Variable) for item in value.values())
            ):
                for variable in value.values():
                    for modes, callback in variable.trace_info():
                        variable.trace_remove(modes, callback)
                value.clear()

    def selected(self, tree):
        ids = list(tree.selection())
        if not ids:
            messagebox.showinfo("Выбор", "Сначала выберите строку в таблице.", parent=self)
        return ids

    def toolbar(self):
        row = ttk.Frame(self)
        row.pack(fill="x", pady=5)
        return row
