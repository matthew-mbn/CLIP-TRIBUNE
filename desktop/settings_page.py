"""Настройки сгруппированы по вкладкам; секреты никогда не возвращаются с API."""

import json
import tkinter as tk
import customtkinter as ctk
import webbrowser
from tkinter import filedialog

from . import theme
from .base import Page
from .source_pages import PRESETS


class SettingsPage(Page):
    title = "Настройки"
    subtitle = "Локальная обработка работает без ключей. Внешние сервисы подключаются по желанию."

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.loaded_once = False
        self.variables = {}
        self.types = {}
        theme.button(self.toolbar(), "Сохранить настройки", self.save, True)
        legal = self.toolbar()
        theme.button(
            legal,
            "Условия использования",
            lambda: webbrowser.open("https://matthew-mbn.github.io/CLIP-TRIBUNE/terms-ru.html"),
        )
        theme.button(
            legal,
            "Конфиденциальность и удаление данных",
            lambda: webbrowser.open("https://matthew-mbn.github.io/CLIP-TRIBUNE/privacy-ru.html"),
        )
        notebook = ctk.CTkTabview(
            self,
            fg_color=theme.PANEL,
            corner_radius=12,
            border_width=1,
            border_color=theme.LINE,
            segmented_button_fg_color=theme.SURFACE,
            segmented_button_selected_color=theme.RED_SOFT,
            segmented_button_selected_hover_color=theme.RED_SOFT,
            segmented_button_unselected_color=theme.SURFACE,
            segmented_button_unselected_hover_color=theme.LINE,
            text_color=theme.WHITE,
            segmented_button_font=("Segoe UI", 13),
            anchor="nw",
        )
        notebook.pack(fill="both", expand=True, pady=10)
        self.tabs = {}
        for name in ("Обработка", "Автоматизация", "Тренды и квоты", "Интеграции", "TikTok", "Диагностика"):
            outer = notebook.add(name)
            tab = ctk.CTkFrame(outer, fg_color=theme.PANEL, corner_radius=0)
            tab.pack(fill="both", expand=True, padx=18, pady=18)
            self.tabs[name] = tab
        process = self.tabs["Обработка"]
        self.add(process, "workers", "Параллельных воркеров", 1, ["1", "2", "3", "4", "6", "8"], int)
        self.add(process, "threads", "Потоков FFmpeg на задачу", 2, ["1", "2", "4", "8", "16"], int)
        self.add(process, "memory_limit_mb", "Лимит RAM процесса, МБ", 4096, cast=int)
        self.add(process, "min_free_gb", "Резерв диска, ГБ", 1, cast=int)
        self.add(process, "resolution", "Разрешение по умолчанию", "1080", ["720", "1080"])
        self.add(process, "source_folder", "Папка исходников", "")
        theme.button(self.row(process), "Выбрать исходники", lambda: self.choose("source_folder"))
        self.add(process, "output_folder", "Папка копий результатов", "")
        theme.button(self.row(process), "Выбрать результаты", lambda: self.choose("output_folder"))
        theme.text(
            process,
            "Уменьшение количества воркеров применяется после перезапуска.\nАппаратные энкодеры определяются в диагностике; MVP использует CPU / libx264.",
            muted=True,
        )
        auto = self.tabs["Автоматизация"]
        self.add(auto, "auto_theme", "Тема автоматических нарезок", "")
        self.add(auto, "auto_preset", "Стиль", "Gaming Viral", PRESETS)
        self.add(auto, "auto_count", "Максимум клипов / исходник", 3, cast=int)
        self.add(auto, "auto_duration", "Длительность, сек.", 30, ["15", "20", "30", "45", "60"], int)
        self.add(auto, "auto_min_score", "Минимальная оценка 0–100", 20, cast=int)
        self.check(auto, "auto_queue", "Добавлять результаты автопроизводства в очередь публикации")
        self.check(auto, "auto_publish", "Автоматически отправлять очередь с выбранным каналом")
        self.check(auto, "allow_public", "Разрешить public (по умолчанию ролики загружаются private)")
        self.channel_names = {}
        self.channel = theme.field(auto, "Канал автопубликации", "Не выбран", ["Не выбран"])
        self.channel_box = auto.winfo_children()[-1].winfo_children()[-1]
        self.saved_channel = ""
        theme.text(
            auto,
            "Запуск производства — на экране «Обзор».\nВключение автопубликации разрешает отправку очереди. По умолчанию она выключена.",
            muted=True,
        )
        trends = self.tabs["Тренды и квоты"]
        self.add(trends, "trend_query", "Автопоиск: тема", "")
        self.add(trends, "trend_region", "Регион: код страны", "US")
        self.add(trends, "trend_hours", "Период, часов", 24, ["1", "6", "24", "168"], int)
        self.add(trends, "trend_interval_minutes", "Интервал, мин. (0=выкл.)", 0, cast=int)
        self.add(trends, "quota_search", "Лимит поиска / день", 100, cast=int)
        self.add(trends, "quota_upload", "Лимит загрузок / день", 100, cast=int)
        self.add(trends, "quota_general", "Остальные единицы / день", 10000, cast=int)
        theme.text(
            trends,
            "Минимальный интервал автоматического поиска — 15 минут.\nУкажите лимиты своего проекта Google Cloud. Счётчики локальные.\nПериод сбрасывается в полночь по Pacific Time.",
            muted=True,
        )
        integrations = self.tabs["Интеграции"]
        self.secret_variables = {}
        labels = {
            "YOUTUBE_API_KEY": "YouTube API key",
            "GOOGLE_CLIENT_ID": "Google OAuth Client ID",
            "GOOGLE_CLIENT_SECRET": "Google OAuth Client Secret",
            "AI_API_URL": "LLM: URL /chat/completions",
            "AI_MODEL": "LLM: имя модели",
            "AI_API_KEY": "LLM: API key",
            "SPEECH_API_URL": "Speech: URL сервиса",
            "SPEECH_API_KEY": "Speech: API key",
        }
        for key, label in labels.items():
            self.secret_variables[key] = theme.field(
                integrations, label, secret=key not in ("AI_API_URL", "AI_MODEL", "SPEECH_API_URL")
            )
        tiktok = self.tabs["TikTok"]
        theme.text(tiktok, "Подключение TikTok", font=("Segoe UI", 20, "bold"))
        for key, label in [
            ("TIKTOK_CLIENT_KEY", "TikTok Client Key"),
            ("TIKTOK_CLIENT_SECRET", "TikTok Client Secret"),
        ]:
            self.secret_variables[key] = theme.field(tiktok, label, secret=True)
        theme.button(self.row(tiktok), "Сохранить ключи TikTok", self.save_secrets, True)
        theme.text(
            tiktok,
            "1. Зарегистрируйте своё приложение в TikTok for Developers.\n"
            "2. Добавьте Login Kit (Desktop) и Content Posting API.\n"
            "3. Redirect URI: http://127.0.0.1:8765/api/tiktok/callback\n"
            "4. Для черновиков нужен video.upload, для Direct Post — video.publish.\n"
            "5. Откройте экран TikTok, выберите способ отправки и подключите аккаунт.\n\n"
            "До аудита Direct Post ограничен приватными аккаунтами и видимостью «Только я».\n"
            "Для публичного доступа требуется одобрение TikTok.\n"
            "Личная утилита только для своих аккаунтов не соответствует условиям аудита Direct Post.\n"
            "В режиме черновика публикация завершается через входящие в TikTok.",
            muted=True,
            wraplength=820,
        )
        theme.button(
            self.row(tiktok),
            "Открыть TikTok Developers",
            lambda: webbrowser.open("https://developers.tiktok.com/"),
        )
        self.configured = theme.text(integrations, "", muted=True, wraplength=800)
        theme.button(self.row(integrations), "Сохранить введённые ключи", self.save_secrets, True)
        theme.text(
            integrations,
            "Google Cloud → YouTube Data API v3 → OAuth consent screen →\nCredentials → OAuth client ID → Desktop app. В режиме Testing добавьте себя в Test users.\nПосле сохранения откройте «Публикация» → «Подключить канал».",
            muted=True,
        )
        theme.button(
            self.row(integrations),
            "Открыть Google Cloud",
            lambda: webbrowser.open("https://console.cloud.google.com/apis/credentials"),
        )
        diagnostics = self.tabs["Диагностика"]
        theme.button(self.row(diagnostics), "Проверить окружение", self.diagnostics, True)
        self.diagnostic_text = tk.Text(
            diagnostics, bg=theme.PANEL, fg=theme.WHITE, relief="flat", wrap="word", height=18
        )
        self.diagnostic_text.pack(fill="both", expand=True, pady=10)

    def row(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x")
        return row

    def add(self, parent, key, label, default, values=None, cast=str):
        self.variables[key] = theme.field(parent, label, default, values)
        self.types[key] = cast

    def check(self, parent, key, label):
        variable = tk.BooleanVar()
        ctk.CTkSwitch(
            parent,
            text=label,
            variable=variable,
            progress_color=theme.RED,
            button_color=theme.WHITE,
            button_hover_color=theme.WHITE,
            fg_color=theme.LINE,
            font=("Segoe UI", 12),
            text_color=theme.WHITE,
        ).pack(anchor="w", pady=9)
        self.variables[key] = variable
        self.types[key] = bool

    def choose(self, key):
        path = filedialog.askdirectory(parent=self)
        if path:
            self.variables[key].set(path)

    def refresh(self, quiet=False):
        if not self.loaded_once:
            self.call("GET", "/settings", callback=self.loaded, quiet=quiet)

    def loaded(self, result):
        self.loaded_once = True
        for key, variable in self.variables.items():
            variable.set(result[key])
        names = [key for key, present in result["configured"].items() if present]
        self.configured.configure(
            text="Настроено: "
            + (", ".join(names) or "пока ничего")
            + ". Пустые поля сохраняют прежние ключи."
        )
        self.saved_channel = result["auto_channel_id"]
        self.call("GET", "/youtube/channels", callback=self.channels_loaded, quiet=True)

    def channels_loaded(self, rows):
        self.channel_names = {f"{row['name']} · {row['youtube_id'][-6:]}": row["id"] for row in rows}
        choices = ["Не выбран", *self.channel_names]
        self.channel_box.configure(values=choices)
        self.channel.set(
            next(
                (name for name, identity in self.channel_names.items() if identity == self.saved_channel),
                "Не выбран",
            )
        )

    def save(self):
        try:
            data = {key: self.types[key](variable.get()) for key, variable in self.variables.items()}
            data["auto_channel_id"] = self.channel_names.get(self.channel.get(), "")
        except ValueError:
            from tkinter import messagebox

            messagebox.showerror("Настройки", "Проверьте числовые значения.", parent=self)
            return
        self.call("PUT", "/settings", data)

    def save_secrets(self):
        values = {
            key: variable.get().strip()
            for key, variable in self.secret_variables.items()
            if variable.get().strip()
        }

        def saved(_):
            for variable in self.secret_variables.values():
                variable.set("")
            self.loaded_once = False
            self.refresh()

        self.call("PUT", "/settings/secrets", {"values": values}, saved)

    def diagnostics(self):
        def show(result):
            self.diagnostic_text.delete("1.0", "end")
            self.diagnostic_text.insert("1.0", json.dumps(result, ensure_ascii=False, indent=2))

        self.call("GET", "/diagnostics", callback=show)
