"""Нижний игровой ролик для прямого эфира."""

import customtkinter as ctk
from . import theme


class GameplayPanel(ctk.CTkFrame):
    def __init__(self, parent, page):
        super().__init__(parent, fg_color="transparent")
        self.page, self.assets = page, {}
        self.asset = theme.field(
            self, "Геймплей снизу", "Выберите исходник", ["Выберите исходник"], stacked=True
        )
        self.selector = self.winfo_children()[-1].winfo_children()[-1]
        self.start = theme.field(self, "Начало геймплея, сек.", "0", stacked=True)
        theme.button(self, "Обновить список исходников", self.refresh)
        theme.text(
            self,
            "Сверху весь стрим с вебкой, снизу геймплей. Звук — из стрима.\nДобавьте игровой файл в «Источниках».",
            muted=True,
            wraplength=370,
        )

    def refresh(self):
        def loaded(rows):
            self.assets = {f"{r['name']} · {r['id'][:6]}": r["id"] for r in rows["assets"]}
            self.selector.configure(values=list(self.assets) or ["Выберите исходник"])

        self.page.call("GET", "/sources", callback=loaded)

    def options(self):
        identity = self.assets.get(self.asset.get())
        if not identity:
            raise ValueError("Выберите файл геймплея для нижней половины")
        return dict(
            layout="split",
            secondary_asset_id=identity,
            secondary_start=float(self.start.get().replace(",", ".")),
            secondary_loop=True,
            split_fit="fit",
            split_audio="top",
        )

    def destroy(self):
        super().destroy()
        self.asset = self.start = None
