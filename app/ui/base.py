"""界面基类：统一异常处理与刷新钩子。"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk

from app.exceptions import DomainError

logger = logging.getLogger(__name__)


class BaseView(ttk.Frame):
    def __init__(self, master: tk.Misc, app, user_id: str) -> None:
        super().__init__(master)
        self.app = app
        self.ctx = app.ctx
        self.user_id = user_id

    # ------------------------------------------------------------------ #
    def guard(self, action, success: str | None = None):
        """执行一次界面操作；业务异常转为提示框，避免界面崩溃。"""
        try:
            result = action()
        except DomainError as exc:
            messagebox.showerror("操作失败", str(exc), parent=self)
            logger.info("业务操作被拒绝：%s", exc)
            return None
        except Exception as exc:  # noqa: BLE001 - 界面层兜底
            logger.exception("界面操作异常")
            messagebox.showerror("系统错误", f"{type(exc).__name__}: {exc}", parent=self)
            return None
        if success:
            self.app.set_status(success)
        self.app.refresh_badge()
        self.safe_refresh()
        return result

    def refresh(self) -> None:
        """子类按需实现。"""

    def safe_refresh(self) -> None:
        try:
            self.refresh()
        except Exception:  # noqa: BLE001 - 刷新失败不应打断用户操作
            logger.exception("界面刷新失败")

    def auto_refresh(self) -> None:
        """定时器调用；默认与手动刷新一致。"""
        self.safe_refresh()


class ModalDialog(tk.Toplevel):
    """模态对话框基类：居中、置顶、Esc 关闭。"""

    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent)
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.configure(background="#F5F6F8")
        self.body = ttk.Frame(self, padding=18)
        self.body.pack(fill="both", expand=True)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.result = None

    def show(self):
        self.update_idletasks()
        parent = self.master.winfo_toplevel()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        self.wait_window()
        return self.result
