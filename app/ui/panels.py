"""跨角色复用的界面面板。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.ui.widgets import add_row, clear_tree, fmt_time, make_table


class MessagePanel(ttk.Frame):
    """消息中心：顾客、商家、骑手共用。"""

    def __init__(self, master: tk.Misc, ctx, user_id: str, app) -> None:
        super().__init__(master, padding=12)
        self.ctx = ctx
        self.user_id = user_id
        self.app = app

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="刷新", command=self.refresh).pack(side="left")
        ttk.Button(toolbar, text="全部标为已读", command=self._mark_all_read).pack(
            side="left", padx=6
        )
        self.frame, self.tree = make_table(
            self,
            [
                ("time", "时间", 110),
                ("title", "标题", 160),
                ("body", "内容", 480),
                ("read", "状态", 60),
            ],
            height=15,
        )
        self.frame.pack(fill="both", expand=True)

    def refresh(self) -> None:
        clear_tree(self.tree)
        for note in self.ctx.notifications.list_for(self.user_id):
            add_row(
                self.tree,
                note.notification_id,
                (
                    fmt_time(note.created_at),
                    note.title,
                    note.body,
                    "已读" if note.read else "未读",
                ),
                tag=None if note.read else "done",
            )

    def _mark_all_read(self) -> None:
        self.ctx.notifications.mark_all_read(self.user_id)
        self.refresh()
        self.app.refresh_badge()
