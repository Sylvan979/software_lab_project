"""界面通用组件：表格、详情面板与表单辅助。"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import ttk

from app.ui.theme import GREEN, MUTED, RED


def make_table(
    parent: tk.Misc,
    columns: list[tuple[str, str, int]],
    *,
    height: int = 10,
    selectmode: str = "browse",
) -> tuple[ttk.Frame, ttk.Treeview]:
    """创建带滚动条的表格；columns 为 (字段名, 表头, 宽度)。"""
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(
        frame,
        columns=[key for key, _, _ in columns],
        show="headings",
        height=height,
        selectmode=selectmode,
    )
    for key, heading, width in columns:
        tree.heading(key, text=heading)
        tree.column(key, width=width, anchor="w", stretch=True)
    tree.tag_configure("done", foreground="#12B76A")
    tree.tag_configure("refund", foreground="#E5484D")
    tree.tag_configure("muted", foreground="#8A909C")
    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    return frame, tree


def clear_tree(tree: ttk.Treeview) -> None:
    for item in tree.get_children():
        tree.delete(item)


def add_row(tree: ttk.Treeview, iid: str, values: tuple, tag: str | None = None) -> None:
    tree.insert("", "end", iid=iid, values=values, tags=(tag,) if tag else ())


def selected_id(tree: ttk.Treeview) -> str | None:
    selection = tree.selection()
    return selection[0] if selection else None


def make_detail(parent: tk.Misc, *, height: int = 8, width: int = 40) -> tk.Text:
    """只读详情面板。"""
    frame = ttk.Frame(parent)
    text = tk.Text(
        frame,
        height=height,
        width=width,
        wrap="word",
        font=("Microsoft YaHei UI", 10),
        background="#FFFFFF",
        foreground="#15171C",
        relief="flat",
        padx=10,
        pady=8,
        borderwidth=0,
        highlightthickness=1,
        highlightbackground="#E1E5EA",
    )
    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=scrollbar.set)
    text.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    text.configure(state="disabled")
    frame.text_widget = text  # type: ignore[attr-defined]
    return frame  # type: ignore[return-value]


def set_detail(widget: tk.Misc, content: str) -> None:
    """``widget`` 可以是 make_detail 返回的容器，也可以是 Text 本身。"""
    text = getattr(widget, "text_widget", widget)
    text.configure(state="normal")
    text.delete("1.0", "end")
    text.insert("1.0", content)
    text.configure(state="disabled")


def add_field(
    parent: tk.Misc,
    row: int,
    column: int,
    label: str,
    variable: tk.Variable,
    *,
    width: int = 18,
    show: str | None = None,
) -> ttk.Entry:
    ttk.Label(parent, text=label, style="Muted.TLabel").grid(
        row=row, column=column, sticky="w", padx=(0, 6), pady=3
    )
    entry = ttk.Entry(parent, textvariable=variable, width=width, show=show or "")
    entry.grid(row=row, column=column + 1, sticky="w", padx=(0, 16), pady=3)
    return entry


def money(value) -> str:
    return f"¥{value:.2f}"


def fmt_time(value: datetime | None) -> str:
    return value.strftime("%m-%d %H:%M") if value else "-"


def tagged(tree: ttk.Treeview) -> ttk.Treeview:
    """为状态行配置颜色标签。"""
    tree.tag_configure("done", foreground=GREEN)
    tree.tag_configure("refund", foreground=RED)
    tree.tag_configure("muted", foreground=MUTED)
    return tree


def status_tag(status_label: str) -> str | None:
    if status_label in ("已完成", "已送达"):
        return "done"
    if status_label in ("已退款", "退款中", "配送失败"):
        return "refund"
    if status_label in ("已取消",):
        return "muted"
    return None
