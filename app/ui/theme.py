"""界面主题：设计令牌与 ttk 样式（延续实验二界面设计规范）。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

BRAND = "#FF6B2C"
BRAND_DARK = "#E8501A"
INK = "#15171C"
MUTED = "#5A6270"
FAINT = "#8A909C"
BG = "#F5F6F8"
CARD = "#FFFFFF"
BORDER = "#E1E5EA"
GREEN = "#12B76A"
BLUE = "#2E6BE6"
ORANGE = "#F79009"
RED = "#E5484D"

FONT_FAMILY = "Microsoft YaHei UI"
BODY = (FONT_FAMILY, 10)
BODY_BOLD = (FONT_FAMILY, 10, "bold")
SMALL = (FONT_FAMILY, 9)
H1 = (FONT_FAMILY, 18, "bold")
H2 = (FONT_FAMILY, 13, "bold")
MONO = ("Consolas", 10)

STATUS_COLORS = {
    "待支付": ORANGE,
    "待接单": ORANGE,
    "制作中": BLUE,
    "待配送": BLUE,
    "配送中": BLUE,
    "已送达": GREEN,
    "已完成": GREEN,
    "已取消": FAINT,
    "退款中": RED,
    "已退款": RED,
    "配送失败": RED,
}


def apply_theme(root: tk.Misc) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", font=BODY, background=BG, foreground=INK)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD, relief="flat")
    style.configure("Header.TFrame", background=CARD)
    style.configure("TLabel", background=BG, foreground=INK)
    style.configure("Card.TLabel", background=CARD, foreground=INK)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=SMALL)
    style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=SMALL)
    style.configure("H1.TLabel", background=CARD, foreground=INK, font=H1)
    style.configure("H2.TLabel", background=BG, foreground=INK, font=H2)
    style.configure("Brand.TLabel", background=CARD, foreground=BRAND, font=H2)
    style.configure("Money.TLabel", background=BG, foreground=BRAND, font=BODY_BOLD)

    style.configure(
        "TButton",
        background=CARD,
        foreground=INK,
        bordercolor=BORDER,
        lightcolor=CARD,
        darkcolor=CARD,
        padding=(12, 6),
    )
    style.map("TButton", background=[("active", "#EDF0F3")])
    style.configure(
        "Accent.TButton",
        background=BRAND,
        foreground="#FFFFFF",
        bordercolor=BRAND,
        lightcolor=BRAND,
        darkcolor=BRAND,
        padding=(14, 7),
    )
    style.map(
        "Accent.TButton",
        background=[("active", BRAND_DARK), ("disabled", "#F5B79C")],
        foreground=[("disabled", "#FFFFFF")],
    )
    style.configure(
        "Danger.TButton",
        background=CARD,
        foreground=RED,
        bordercolor="#F3C2C2",
        lightcolor=CARD,
        darkcolor=CARD,
    )
    style.configure("Link.TButton", background=BG, foreground=BLUE, borderwidth=0)
    style.map("Link.TButton", background=[("active", BG)])

    style.configure(
        "Treeview",
        background=CARD,
        fieldbackground=CARD,
        foreground=INK,
        rowheight=27,
        borderwidth=0,
    )
    style.configure(
        "Treeview.Heading",
        background="#EEF1F4",
        foreground=MUTED,
        font=BODY_BOLD,
        relief="flat",
    )
    style.map("Treeview", background=[("selected", "#FFE7DB")], foreground=[("selected", INK)])
    style.map("Treeview.Heading", background=[("active", "#E4E8EC")])

    style.configure("TEntry", fieldbackground=CARD, bordercolor=BORDER, padding=4)
    style.configure("TCombobox", fieldbackground=CARD, padding=4)
    style.configure(
        "TNotebook", background=BG, borderwidth=0, tabmargins=(12, 8, 12, 0)
    )
    style.configure("TNotebook.Tab", padding=(18, 8), font=BODY)
    style.map(
        "TNotebook.Tab",
        background=[("selected", CARD), ("!selected", "#E9ECEF")],
        foreground=[("selected", BRAND), ("!selected", MUTED)],
    )
    style.configure("TLabelframe", background=BG, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=BG, foreground=MUTED, font=SMALL)
    style.configure("TCheckbutton", background=BG)
    style.configure("Card.TCheckbutton", background=CARD)
