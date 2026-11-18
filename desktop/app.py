"""Точка входа интерфейса и безопасная доставка результатов фоновых потоков."""

import queue
import tkinter as tk
import customtkinter as ctk
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from tkinter import messagebox, ttk

from . import client, theme


class Application(ctk.CTk):
    def __init__(self, api=client.request):
        super().__init__()
        self.title("CLIP TRIBUNE — студия коротких видео")
        self.geometry("1440x920")
        self.minsize(1100, 720)
        theme.configure(self)
        self.logo_icon = theme.window_icon(self)
        self.api = api
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.results = queue.Queue()
        self.callbacks = {}
        self.task_number = 0
        self.page = None
        self.current_page = ""
        self.closed = False
        self.pending = 0
        self.status = tk.StringVar(value="Локальное рабочее пространство")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.build_shell()
        self.show_page("Обзор")
        self.after(100, self.receive_results)
        self.after(3000, self.poll)
        self.async_call("GET", "/settings", callback=self.first_launch)

    def build_shell(self):
        sidebar = ctk.CTkFrame(self, fg_color=theme.SIDEBAR, width=228, corner_radius=0)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=22, pady=(25, 25))
        theme.logo(brand, size=32, background=theme.SIDEBAR).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(brand, text="CLIP TRIBUNE", text_color=theme.WHITE, font=("Segoe UI", 17, "bold")).pack(
            side="left"
        )
        workspace = ctk.CTkFrame(
            sidebar, fg_color=theme.PANEL, corner_radius=10, border_width=1, border_color=theme.LINE
        )
        workspace.pack(fill="x", padx=16, pady=(0, 24))
        ctk.CTkLabel(
            workspace,
            text="CT",
            width=34,
            height=34,
            corner_radius=8,
            fg_color=theme.RED_SOFT,
            text_color=theme.RED,
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left", padx=12, pady=12)
        ctk.CTkLabel(
            workspace,
            text="Личная студия\nЛокальное пространство",
            justify="left",
            anchor="w",
            text_color=theme.MUTED,
            font=("Segoe UI", 11),
        ).pack(side="left")
        ctk.CTkLabel(
            sidebar, text="РАБОЧЕЕ ПРОСТРАНСТВО", text_color="#686b75", font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", padx=26, pady=(0, 8))
        self.navigation = {}
        symbols = dict(
            Обзор="▦",
            Источники="⊞",
            Эфиры="●",
            Тренды="⌁",
            Студия="✦",
            Реклама="◈",
            Очередь="≡",
            Библиотека="▣",
            Публикация="↗",
            TikTok="♪",
            Анимация="◇",
            Настройки="⚙",
        )
        menu = ctk.CTkScrollableFrame(
            sidebar, fg_color="transparent", corner_radius=0, scrollbar_button_color=theme.LINE
        )
        menu.pack(fill="both", expand=True)
        for label, symbol in symbols.items():
            if label == "Публикация":
                ctk.CTkLabel(
                    menu, text="УПРАВЛЕНИЕ", text_color="#686b75", font=("Segoe UI", 10, "bold")
                ).pack(anchor="w", padx=26, pady=(22, 8))
            item = ctk.CTkButton(
                menu,
                text=f"  {symbol}    {label}",
                anchor="w",
                height=42,
                corner_radius=8,
                border_width=0,
                fg_color="transparent",
                text_color=theme.MUTED,
                hover_color=theme.SURFACE,
                font=("Segoe UI", 13),
                command=lambda name=label: self.show_page(name),
            )
            item.pack(fill="x", padx=14, pady=3)
            self.navigation[label] = item
        ctk.CTkLabel(
            sidebar, text="СВОИ МАТЕРИАЛЫ. СВОЯ ТРИБУНА.", text_color="#646772", font=("Segoe UI", 9)
        ).pack(side="bottom", pady=22)
        tip = ctk.CTkFrame(sidebar, fg_color=theme.PANEL, corner_radius=12)
        tip.pack(side="bottom", fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            tip, text="Всё остаётся у вас", text_color=theme.WHITE, font=("Segoe UI", 13, "bold")
        ).pack(anchor="w", padx=16, pady=(15, 2))
        ctk.CTkLabel(
            tip,
            text="Ваши файлы. Ваш компьютер.\nПубликация под вашим контролем.",
            justify="left",
            text_color=theme.MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=16, pady=(0, 16))
        ctk.CTkFrame(self, width=1, fg_color=theme.LINE, corner_radius=0).pack(side="left", fill="y")
        area = ctk.CTkFrame(self, fg_color=theme.BLACK, corner_radius=0)
        area.pack(fill="both", expand=True)
        header = ctk.CTkFrame(area, fg_color=theme.BLACK, corner_radius=0, height=72)
        header.pack(fill="x", padx=32, pady=(12, 10))
        self.breadcrumb = ctk.CTkLabel(
            header, text="Студия  /  Обзор", text_color=theme.MUTED, font=("Segoe UI", 12)
        )
        self.breadcrumb.pack(side="left")
        ctk.CTkButton(
            header,
            text="■   Остановить всё",
            command=self.stop_all,
            width=150,
            height=34,
            corner_radius=7,
            fg_color=theme.BLACK,
            hover_color=theme.RED_SOFT,
            border_width=1,
            border_color=theme.LINE,
            text_color=theme.MUTED,
            font=("Segoe UI", 12),
        ).pack(side="right", pady=8)
        ctk.CTkLabel(header, text="●  Локальная студия", text_color=theme.MUTED, font=("Segoe UI", 11)).pack(
            side="right", padx=20
        )
        ctk.CTkFrame(area, height=1, fg_color=theme.LINE, corner_radius=0).pack(fill="x")
        footer = ctk.CTkFrame(area, fg_color=theme.BLACK, height=32, corner_radius=0)
        footer.pack(side="bottom", fill="x", padx=32, pady=8)
        ctk.CTkLabel(
            footer, textvariable=self.status, text_color="#737682", font=("Segoe UI", 11), height=18
        ).pack(side="left")
        # Canvas даёт вертикальную прокрутку длинным формам на небольшом экране.
        content = ttk.Frame(area)
        content.pack(fill="both", expand=True)
        self.viewport = tk.Canvas(content, bg=theme.BLACK, highlightthickness=0)
        scrollbar = ctk.CTkScrollbar(
            content,
            orientation="vertical",
            command=self.viewport.yview,
            width=10,
            button_color=theme.LINE,
            button_hover_color=theme.MUTED,
            fg_color=theme.BLACK,
        )
        scrollbar.pack(side="right", fill="y")
        self.viewport.pack(side="left", fill="both", expand=True)
        self.viewport.configure(yscrollcommand=scrollbar.set)
        self.body = ttk.Frame(self.viewport, padding=(32, 26))
        body_window = self.viewport.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind(
            "<Configure>", lambda _: self.viewport.configure(scrollregion=self.viewport.bbox("all"))
        )
        self.viewport.bind(
            "<Configure>", lambda event: self.viewport.itemconfigure(body_window, width=event.width)
        )
        self.bind_all("<MouseWheel>", self.scroll_page)

    def scroll_page(self, event):
        if not isinstance(event.widget, (tk.Text, ttk.Treeview, ttk.Combobox)):
            self.viewport.yview_scroll(-int(event.delta / 120), "units")

    def show_page(self, name):
        from .pages import PAGES

        if self.page:
            self.page.destroy()
        self.current_page = name
        self.breadcrumb.configure(text="Студия   /   " + name)
        for label, item in self.navigation.items():
            item.configure(
                fg_color=theme.RED_SOFT if name == label else "transparent",
                text_color=theme.RED if name == label else theme.MUTED,
            )
        self.page = PAGES[name](self.body, self)
        self.page.pack(fill="both", expand=True)
        self.viewport.yview_moveto(0)
        self.page.refresh()

    def async_call(self, method, path, data=None, callback=None, quiet=False):
        self.background(partial(self.api, method, path, data), callback, quiet)

    def background(self, function, callback=None, quiet=False):
        # Tkinter разрешает менять виджеты только из главного потока.
        self.pending += 1
        if not quiet:
            self.status.set("Выполняется операция…")
        self.task_number += 1
        task_id = self.task_number
        self.callbacks[task_id] = (callback, quiet)
        results_queue = self.results
        future = self.executor.submit(function)
        # Callback воркера не захватывает окно/страницу. Иначе последний объект
        # StringVar может уничтожиться в чужом потоке и заблокировать Tcl.
        future.add_done_callback(lambda done: results_queue.put((task_id, done)))

    def receive_results(self):
        if self.closed:
            return
        while True:
            try:
                task_id, future = self.results.get_nowait()
            except queue.Empty:
                break
            self.pending -= 1
            callback, quiet = self.callbacks.pop(task_id)
            try:
                result = future.result()
                if callback:
                    callback(result)
                if not quiet:
                    self.status.set("Готово")
            except tk.TclError:
                # Пользователь мог уйти со страницы до завершения HTTP-запроса.
                pass
            except Exception as error:
                self.status.set(str(error)[:180])
                if not quiet:
                    messagebox.showerror("CLIP TRIBUNE", str(error), parent=self)
        self.after(100, self.receive_results)

    def poll(self):
        if self.closed:
            return
        if self.page and self.pending < 3:
            self.page.refresh(quiet=True)
        self.after(3000, self.poll)

    def first_launch(self, settings):
        if not settings["onboarded"]:
            from .onboarding import Onboarding

            Onboarding(self)

    def stop_all(self):
        self.async_call("POST", "/control/stop", callback=lambda _: self.page.refresh())

    def close(self):
        self.closed = True
        self.executor.shutdown(wait=False, cancel_futures=True)
        # Ссылки на страницы и Tk-переменные освобождаем именно в UI-потоке.
        # Поздний сборщик мусора может работать в потоке HTTP-запроса.
        self.callbacks.clear()
        self.destroy()
        self.page = None
        self.navigation.clear()
        self.status = None
        self.logo_icon = None


def main():
    Application().mainloop()


if __name__ == "__main__":
    main()
