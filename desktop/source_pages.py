"""Источники и студия: от выбора файла до постановки задачи в очередь."""

import tkinter as tk
import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

from . import theme
from .base import Page

PRESETS = ["Gaming Viral", "Funny Moments", "Cinematic", "Action", "Storytelling", "Educational", "Custom"]
FRAMING = {"Размытый фон": "blur", "Вертикальная обрезка": "crop", "Исходные пропорции": "original"}


class SourcesPage(Page):
    title = "Источники"
    subtitle = "Импортируйте свои видео. Оригиналы остаются на месте; студия работает с копиями."

    def __init__(self, parent, app):
        super().__init__(parent, app)
        row = self.toolbar()
        theme.button(row, "+ Добавить видео", self.import_files, True)
        theme.button(row, "Импорт папки", lambda: self.folder(False))
        theme.button(row, "Отслеживать папку", lambda: self.folder(True))
        theme.button(row, "Прямая ссылка", self.remote)
        download_panel = ctk.CTkFrame(
            self, fg_color=theme.PANEL, corner_radius=12, border_width=1, border_color=theme.LINE
        )
        download_panel.pack(fill="x", pady=(15, 8))
        download_body = ctk.CTkFrame(download_panel, fg_color="transparent")
        download_body.pack(fill="x", padx=20, pady=16)
        theme.text(download_body, "YouTube / Twitch", font=("Segoe UI", 16, "bold"))
        self.download_url = theme.field(download_body, "Ссылка на видео, Shorts или клип", stacked=True)
        self.download_height = theme.field(download_body, "Качество до", "1080", ["720", "1080"])
        self.download_rights = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            download_body,
            text="У меня есть права на скачивание и монтаж этого видео",
            variable=self.download_rights,
            fg_color=theme.RED,
            hover_color=theme.RED_SOFT,
            font=("Segoe UI", 12),
        ).pack(anchor="w", pady=10)
        theme.text(
            download_body,
            "Один публичный ролик по ссылке. Twitch: записи и клипы. Прогресс и отмена — в очереди.",
            muted=True,
            wraplength=850,
            font=("Segoe UI", 11),
        )
        theme.button(download_body, "↓ Скачать в источники", self.download, True)
        self.tree = theme.table(
            self,
            [
                ("name", "Исходник"),
                ("duration", "Секунды"),
                ("size", "Разрешение"),
                ("audio", "Звук"),
                ("rights", "Права"),
            ],
            8,
        )
        row = self.toolbar()
        theme.button(row, "Подтвердить права", self.rights)
        theme.button(row, "Открыть студию", lambda: app.show_page("Студия"))
        self.folders = theme.table(self, [("path", "Отслеживаемая папка"), ("state", "Состояние")], 3)
        theme.button(self.toolbar(), "Остановить наблюдение", self.unwatch)
        self.notice = theme.text(self, "", muted=True, wraplength=850)

    def refresh(self, quiet=False):
        self.call("GET", "/sources", callback=self.loaded, quiet=quiet)

    def download(self):
        self.call(
            "POST",
            "/sources/download",
            dict(
                url=self.download_url.get().strip(),
                height=int(self.download_height.get()),
                rights=self.download_rights.get(),
            ),
            lambda _: self.call(
                "POST", "/control/resume-queue", callback=lambda _: self.app.show_page("Очередь")
            ),
        )

    def loaded(self, result):
        theme.replace_rows(
            self.tree,
            [
                (
                    a["id"],
                    (
                        a["name"],
                        round(a["metadata_json"]["duration"], 1),
                        f"{a['metadata_json']['width']} × {a['metadata_json']['height']}",
                        "Да" if a["metadata_json"]["audio"] else "Нет",
                        "Подтверждены" if a["rights"] else "Не подтверждены",
                    ),
                )
                for a in result["assets"]
            ],
        )
        theme.replace_rows(
            self.folders,
            [
                (f["id"], (f["path"], "Наблюдение" if f["watching"] else "Остановлено"))
                for f in result["folders"]
            ],
        )

    def rights_question(self):
        return messagebox.askyesno(
            "Права на материалы",
            "Вы владеете этими материалами или имеете разрешение на монтаж и публикацию?\n\nБез подтверждения их можно импортировать, но нельзя монтировать.",
            parent=self,
        )

    def import_files(self):
        files = filedialog.askopenfilenames(parent=self, filetypes=[("Видео", "*.mp4 *.mov *.mkv *.webm")])
        if files:
            self.import_paths(list(files), self.rights_question())

    def import_paths(self, paths, rights):
        def imported(result):
            self.notice.configure(
                text=f"Импортировано: {len(result['assets'])}. "
                + "\n".join(e["name"] + ": " + e["error"] for e in result["errors"])
            )
            self.refresh()

        self.call("POST", "/sources/local", dict(paths=paths, rights=rights), imported)

    def folder(self, watching):
        folder = filedialog.askdirectory(parent=self)
        if not folder:
            return
        rights = self.rights_question()
        if watching:
            self.call(
                "POST",
                "/sources/folder",
                dict(path=folder, watching=True, rights=rights),
                lambda _: self.refresh(),
            )
        else:
            paths = [
                str(p)
                for p in Path(folder).iterdir()
                if p.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm")
            ]
            if not paths:
                messagebox.showinfo("Импорт", "В папке нет поддерживаемых видео.", parent=self)
            else:
                self.import_paths(paths[:100], rights)

    def remote(self):
        url = simpledialog.askstring(
            "Прямой медиафайл", "HTTPS-ссылка на MP4 / MOV / MKV / WEBM (не страница YouTube):", parent=self
        )
        if url:
            self.call(
                "POST",
                "/sources/remote",
                dict(url=url, rights=self.rights_question()),
                lambda _: self.app.show_page("Очередь"),
            )

    def rights(self):
        selected = self.selected(self.tree)
        if selected and self.rights_question():
            for identity in selected:
                self.call("POST", f"/sources/{identity}/rights", callback=lambda _: self.refresh())

    def unwatch(self):
        for identity in self.selected(self.folders):
            self.call("DELETE", f"/sources/folders/{identity}", callback=lambda _: self.refresh())


class StudioPage(Page):
    title = "Студия нарезок"
    subtitle = "Выберите исходники и настройте монтаж. Ctrl + клик позволяет выбрать несколько видео."

    def __init__(self, parent, app):
        from .webcam import WebcamPanel

        super().__init__(parent, app)
        self.preselected = None
        layout = ctk.CTkFrame(self, fg_color="transparent")
        layout.pack(fill="x", pady=(18, 0))
        layout.columnconfigure(0, weight=1)
        layout.columnconfigure(1, weight=0, minsize=330)
        source_panel = ctk.CTkFrame(
            layout, fg_color=theme.PANEL, corner_radius=12, border_width=1, border_color=theme.LINE
        )
        source_panel.grid(row=0, column=0, sticky="new", padx=(0, 20))
        source_body = ctk.CTkFrame(source_panel, fg_color="transparent")
        source_body.pack(fill="both", expand=True, padx=22, pady=20)
        theme.text(source_body, "01  /  Ваши исходники", font=("Segoe UI", 16, "bold"))
        theme.text(source_body, "Выберите один или несколько файлов для этой серии.", muted=True)
        self.tree = theme.table(
            source_body, [("name", "Исходник"), ("duration", "Длительность"), ("rights", "Права")], 5
        )
        add_row = ctk.CTkFrame(source_body, fg_color="transparent")
        add_row.pack(fill="x", pady=(0, 14))
        theme.button(add_row, "+ Добавить исходники", lambda: app.show_page("Источники"))
        self.theme = theme.field(source_body, "Тема / название серии", stacked=True)
        ctk.CTkFrame(source_body, height=1, fg_color=theme.LINE).pack(fill="x", pady=18)
        theme.text(source_body, "Два видео в одном кадре", font=("Segoe UI", 16, "bold"))
        self.layout_mode = theme.field(
            source_body,
            "Экран",
            "Один ролик",
            ["Один ролик", "Два ролика: верх / низ", "Видео + вебка · 50/50"],
            stacked=True,
        )
        self.split_panel = ctk.CTkFrame(source_body, fg_color="transparent")
        self.secondary = theme.field(
            self.split_panel, "Нижнее видео", "Выберите исходник", ["Выберите исходник"], stacked=True
        )
        self.secondary_widget = self.split_panel.winfo_children()[-1].winfo_children()[-1]
        self.secondary_assets = {}
        self.secondary_start = theme.field(
            self.split_panel, "Начать нижнее видео с секунды", "0", stacked=True
        )
        self.split_fit = theme.field(
            self.split_panel,
            "Заполнение половин",
            "Обрезать по центру",
            ["Обрезать по центру", "Вписать целиком"],
            stacked=True,
        )
        self.split_audio = theme.field(
            self.split_panel,
            "Звук",
            "Верхний ролик",
            ["Верхний ролик", "Нижний ролик", "Оба ролика", "Без звука"],
            stacked=True,
        )
        self.secondary_loop = tk.BooleanVar(value=True)
        ctk.CTkSwitch(
            self.split_panel,
            text="Повторять нижнее видео с точки начала",
            variable=self.secondary_loop,
            progress_color=theme.RED,
            font=("Segoe UI", 12),
        ).pack(anchor="w", pady=10)
        theme.text(
            self.split_panel,
            "Верх — выбранные исходники из таблицы. Низ — второй ролик.\nИтог: вертикальный экран 9:16, две равные половины.",
            muted=True,
            wraplength=450,
            font=("Segoe UI", 11),
        )
        # Панель появляется на своём месте; прочие настройки остаются доступны.
        self.webcam = WebcamPanel(source_body, self, self.webcam_source)
        self.split_anchor = ctk.CTkFrame(source_body, height=1, fg_color=theme.LINE)
        self.split_anchor.pack(fill="x", pady=12)
        self.layout_mode.trace_add("write", lambda *_: self.change_layout())
        ctk.CTkFrame(source_body, height=1, fg_color=theme.LINE).pack(fill="x", pady=20)
        theme.text(source_body, "Понятный процесс. Настоящий результат.", font=("Segoe UI", 14, "bold"))
        for number, title, description in [
            ("1", "Анализ", "Движение в кадре, смены сцен и звуковые пики."),
            ("2", "Отбор", "Уникальные фрагменты без пересечения по времени."),
            ("3", "Экспорт", "Готовые вертикальные ролики в вашей библиотеке."),
        ]:
            step = ctk.CTkFrame(source_body, fg_color="transparent")
            step.pack(fill="x", pady=7)
            ctk.CTkLabel(
                step,
                text=number,
                width=28,
                height=28,
                fg_color=theme.SURFACE,
                corner_radius=8,
                text_color=theme.MUTED,
                font=("Segoe UI", 12),
            ).pack(side="left", padx=(0, 12))
            ctk.CTkLabel(
                step,
                text=title + "  ·  " + description,
                text_color=theme.MUTED,
                font=("Segoe UI", 11),
                anchor="w",
            ).pack(side="left")
        settings_panel = ctk.CTkFrame(
            layout, fg_color=theme.PANEL, corner_radius=12, border_width=1, border_color=theme.LINE
        )
        settings_panel.grid(row=0, column=1, sticky="new")
        form = ctk.CTkFrame(settings_panel, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=22, pady=20)
        theme.text(form, "02  /  Параметры нарезки", font=("Segoe UI", 16, "bold"))
        self.preset = theme.field(form, "Стиль монтажа", "Gaming Viral", PRESETS, width=32, stacked=True)
        self.count = theme.field(
            form,
            "Нарезок на исходник",
            "3",
            [str(i) for i in (1, 2, 3, 5, 10, 20, 30)],
            width=32,
            stacked=True,
        )
        self.duration = theme.field(
            form, "Продолжительность, сек.", "30", ["15", "20", "30", "45", "60"], width=32, stacked=True
        )
        self.resolution = theme.field(
            form, "Ширина экспорта", "1080", ["720", "1080"], width=32, stacked=True
        )
        self.framing = theme.field(form, "Композиция", "Размытый фон", list(FRAMING), width=32, stacked=True)
        self.framing_widget = form.winfo_children()[-1].winfo_children()[-1]
        self.subtitles = tk.BooleanVar()
        self.overlay = tk.BooleanVar()
        self.use_ads = tk.BooleanVar(value=True)
        for label, variable in [("Добавить субтитры", self.subtitles), ("Тема поверх видео", self.overlay)]:
            ctk.CTkSwitch(
                form,
                text=label,
                variable=variable,
                progress_color=theme.RED,
                fg_color=theme.LINE,
                button_color=theme.WHITE,
                font=("Segoe UI", 12),
            ).pack(anchor="w", pady=9)
        ctk.CTkSwitch(
            form,
            text="Реклама из сохранённых настроек",
            variable=self.use_ads,
            progress_color=theme.RED,
            font=("Segoe UI", 11),
        ).pack(anchor="w", pady=9)
        self.ad_status = theme.text(
            form, "Реклама: проверка настроек…", muted=True, wraplength=255, font=("Segoe UI", 11)
        )
        theme.button(form, "Настроить рекламу", lambda: app.show_page("Реклама"))
        # Отдельный контейнер не даёт кнопке с side=left сдвинуть форму экспорта.
        form.winfo_children()[-1].pack_configure(side="top", anchor="w")
        ctk.CTkLabel(
            form,
            text="Субтитрам нужен подключённый SpeechProvider.",
            font=("Segoe UI", 10),
            text_color=theme.MUTED,
        ).pack(anchor="w", pady=(0, 12))
        ctk.CTkButton(
            form,
            text="✦  Создать нарезки",
            command=self.create,
            height=42,
            corner_radius=8,
            fg_color=theme.RED,
            hover_color="#d83444",
            font=("Segoe UI", 13, "bold"),
        ).pack(fill="x")
        ctk.CTkLabel(
            form, text="MP4  ·  H.264  ·  AAC  ·  30 FPS", text_color=theme.MUTED, font=("Segoe UI", 10)
        ).pack(pady=(8, 0))
        theme.text(
            self,
            "Отбор основан на движении и звуке. Если уникальных моментов мало, роликов будет меньше. Проверьте результат перед публикацией.",
            muted=True,
            wraplength=1000,
        )
        self.call(
            "GET", "/settings", callback=lambda config: self.resolution.set(config["resolution"]), quiet=True
        )
        self.call(
            "GET",
            "/ads",
            callback=lambda result: self.ad_status.configure(
                text="Реклама включена в разделе «Реклама»"
                if result["config"]["enabled"]
                else "Реклама выключена в разделе «Реклама»"
            ),
            quiet=True,
        )

    def change_layout(self):
        self.split_panel.pack_forget()
        self.webcam.pack_forget()
        if self.layout_mode.get() == "Один ролик":
            self.framing_widget.configure(state="readonly")
        else:
            panel = self.webcam if self.layout_mode.get() == "Видео + вебка · 50/50" else self.split_panel
            panel.pack(fill="x", before=self.split_anchor)
            self.framing_widget.configure(state="disabled")

    def webcam_source(self):
        selected = self.tree.selection()
        if len(selected) != 1:
            raise ValueError("Для вебки выберите один исходник в таблице")
        return dict(asset_id=selected[0])

    def refresh(self, quiet=False):
        self.call("GET", "/sources", callback=self.loaded, quiet=quiet)

    def loaded(self, result):
        self.secondary_assets = {
            f"{a['name']} · {a['id'][:6]}": a["id"] for a in result["assets"] if a["rights"]
        }
        self.secondary_widget.configure(values=list(self.secondary_assets) or ["Выберите исходник"])
        theme.replace_rows(
            self.tree,
            [
                (
                    a["id"],
                    (
                        a["name"],
                        f"{a['metadata_json']['duration']:.0f} сек.",
                        "Подтверждены" if a["rights"] else "Нужно подтвердить",
                    ),
                )
                for a in result["assets"]
            ],
        )
        if self.preselected and self.tree.exists(self.preselected):
            self.tree.selection_set(self.preselected)
            self.preselected = None

    def create(self):
        selected = self.selected(self.tree)
        if selected:
            split = self.layout_mode.get() == "Два ролика: верх / низ"
            try:
                offset = float(self.secondary_start.get().replace(",", ".")) if split else 0
                webcam = self.webcam.options() if self.layout_mode.get() == "Видео + вебка · 50/50" else {}
            except ValueError as error:
                messagebox.showerror("Студия", str(error), parent=self)
                return
            data = dict(
                asset_ids=selected,
                theme=self.theme.get(),
                count=int(self.count.get()),
                duration=int(self.duration.get()),
                preset=self.preset.get(),
                resolution=self.resolution.get(),
                framing=FRAMING[self.framing.get()],
                subtitles=self.subtitles.get(),
                title_overlay=self.overlay.get(),
                use_ads=self.use_ads.get(),
                layout="split" if split else "single",
                secondary_asset_id=self.secondary_assets.get(self.secondary.get()) if split else None,
                secondary_start=offset,
                secondary_loop=self.secondary_loop.get(),
                split_fit="crop" if self.split_fit.get() == "Обрезать по центру" else "fit",
                split_audio={
                    "Верхний ролик": "top",
                    "Нижний ролик": "bottom",
                    "Оба ролика": "mix",
                    "Без звука": "mute",
                }[self.split_audio.get()],
            )
            data.update(webcam)
            self.call("POST", "/jobs", data, lambda _: self.resume_and_open())

    def resume_and_open(self):
        self.call("POST", "/control/resume-queue", callback=lambda _: self.app.show_page("Очередь"))
