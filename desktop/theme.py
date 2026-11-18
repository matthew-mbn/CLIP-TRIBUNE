"""Все цвета и общие элементы находятся здесь — удобно менять оформление."""

import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

BLACK = "#101114"
PANEL = "#18191d"
SURFACE = "#222329"
LINE = "#2c2d34"
WHITE = "#f7f7f9"
MUTED = "#93959f"
RED = "#f04452"
RED_SOFT = "#352027"
SIDEBAR = "#141518"


def configure(root):
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    if isinstance(root, ctk.CTk):
        root.configure(fg_color=BLACK)
    else:
        root.configure(bg=BLACK)
    root.option_add("*Font", ("Segoe UI", 10))
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BLACK, foreground=WHITE, fieldbackground=SURFACE)
    style.configure("TFrame", background=BLACK)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("TLabel", background=BLACK, foreground=WHITE)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Title.TLabel", font=("Segoe UI", 26, "bold"))
    style.configure("Heading.TLabel", font=("Segoe UI", 13, "bold"))
    style.configure("TButton", padding=(14, 9), background=SURFACE, foreground=WHITE, borderwidth=0)
    style.map("TButton", background=[("active", LINE), ("disabled", PANEL)], foreground=[("disabled", MUTED)])
    style.configure("Accent.TButton", background=RED, foreground=WHITE)
    style.map("Accent.TButton", background=[("active", "#cd2532")])
    style.configure("TEntry", fieldbackground=SURFACE, foreground=WHITE, insertcolor=WHITE, padding=8)
    style.configure("TCombobox", fieldbackground=SURFACE, foreground=WHITE, padding=7, arrowcolor=WHITE)
    style.map("TCombobox", fieldbackground=[("readonly", SURFACE)], foreground=[("readonly", WHITE)])
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", WHITE)
    style.configure("TCheckbutton", background=BLACK, foreground=WHITE, padding=5)
    style.map("TCheckbutton", background=[("active", PANEL)])
    style.configure(
        "Treeview",
        background=PANEL,
        fieldbackground=PANEL,
        foreground=WHITE,
        rowheight=44,
        borderwidth=0,
        font=("Segoe UI", 10),
    )
    # Убираем нативные рамки: таблица живёт внутри общей скруглённой панели.
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.configure(
        "Treeview.Heading",
        background=PANEL,
        foreground=MUTED,
        padding=(12, 12),
        relief="flat",
        font=("Segoe UI", 9),
        borderwidth=0,
    )
    style.layout(
        "Treeview.Heading",
        [("Treeheading.padding", {"sticky": "nswe", "children": [("Treeheading.text", {"sticky": "w"})]})],
    )
    style.map("Treeview", background=[("selected", RED_SOFT)], foreground=[("selected", WHITE)])
    style.configure("Horizontal.TProgressbar", troughcolor=SURFACE, background=RED)
    style.configure("TNotebook", background=BLACK, borderwidth=0)
    style.configure("TNotebook.Tab", padding=(18, 10), background=SURFACE, foreground=WHITE)
    style.map("TNotebook.Tab", background=[("selected", RED)])


def logo(parent, size=44, background=PANEL):
    """Один и тот же фирменный знак в интерфейсе и в исполняемом файле."""
    from PIL import Image
    from backend.config import ROOT

    icon = ctk.CTkImage(Image.open(ROOT / "assets" / "logo.png"), size=(size, size))
    return ctk.CTkLabel(parent, text="", image=icon, width=size, height=size, fg_color=background)


def window_icon(root):
    import sys
    from PIL import Image, ImageTk
    from backend.config import ROOT

    icon = ImageTk.PhotoImage(Image.open(ROOT / "assets" / "logo.png").resize((64, 64)), master=root)
    root.iconphoto(True, icon)
    if sys.platform == "win32":
        # iconbitmap сообщает CTk, что пользовательская иконка уже назначена.
        # Иначе CTk позднее вернёт свой синий значок в заголовок Windows.
        root.iconbitmap(str(ROOT / "assets" / "app.ico"))
    return icon


def text(parent, value, muted=False, **kwargs):
    kwargs.pop("style", None)
    kwargs.setdefault("font", ("Segoe UI", 13))
    label = ctk.CTkLabel(
        parent,
        text=value,
        text_color=MUTED if muted else WHITE,
        anchor="w",
        justify="left",
        height=22,
        **kwargs,
    )
    label.pack(anchor="w", pady=(0, 10))
    return label


def button(parent, label, command, accent=False):
    widget = ctk.CTkButton(
        parent,
        text=label,
        command=command,
        width=max(108, len(label) * 7 + 24),
        height=38,
        corner_radius=8,
        fg_color=RED if accent else PANEL,
        hover_color="#d83444" if accent else SURFACE,
        text_color=WHITE,
        border_color=LINE,
        border_width=0 if accent else 1,
        font=("Segoe UI", 13, "bold" if accent else "normal"),
    )
    widget.pack(side="left", padx=(0, 8), pady=5)
    return widget


def field(parent, label, default="", values=None, width=35, secret=False, stacked=False):
    row = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
    row.pack(fill="x", pady=5)
    ctk.CTkLabel(
        row, text=label, width=0 if stacked else 230, text_color=MUTED, font=("Segoe UI", 12), anchor="w"
    ).pack(side="top" if stacked else "left", anchor="w", pady=(0, 5) if stacked else 0)
    variable = tk.StringVar(value=str(default))
    if values:
        entry = ctk.CTkComboBox(
            row,
            variable=variable,
            values=values,
            state="readonly",
            width=width * 8,
            height=38,
            corner_radius=8,
            fg_color=PANEL,
            border_color=LINE,
            border_width=1,
            button_color=SURFACE,
            button_hover_color=LINE,
            dropdown_fg_color=PANEL,
            dropdown_hover_color=RED_SOFT,
            text_color=WHITE,
            dropdown_text_color=WHITE,
            font=("Segoe UI", 13),
            dropdown_font=("Segoe UI", 13),
        )
    else:
        entry = ctk.CTkEntry(
            row,
            textvariable=variable,
            width=width * 8,
            show="•" if secret else "",
            height=38,
            corner_radius=8,
            fg_color=PANEL,
            border_color=LINE,
            border_width=1,
            text_color=WHITE,
            font=("Segoe UI", 13),
        )
    entry.pack(side="top" if stacked else "left", fill="x", expand=True)
    return variable


def table(parent, columns, height=9):
    container = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=12, border_width=1, border_color=LINE)
    container.pack(fill="both", expand=True, pady=12)
    tree = ttk.Treeview(
        container, columns=[key for key, _ in columns], show="headings", height=height, selectmode="extended"
    )
    for key, label in columns:
        tree.heading(key, text=label)
        tree.column(key, width=120, minwidth=70, stretch=True)
    scrollbar = ctk.CTkScrollbar(
        container,
        orientation="vertical",
        command=tree.yview,
        fg_color=PANEL,
        button_color=LINE,
        button_hover_color=MUTED,
        width=10,
    )
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y", padx=(0, 6), pady=12)
    tree.pack(fill="both", expand=True, padx=(12, 4), pady=10)
    return tree


def replace_rows(tree, rows):
    """Сохраняем выделение при обновлении прогресса каждые несколько секунд."""
    selected = tree.selection()
    for identity in tree.get_children():
        tree.delete(identity)
    for identity, values in rows:
        tree.insert("", "end", iid=identity, values=values)
    for identity in selected:
        if tree.exists(identity):
            tree.selection_add(identity)
