"""主窗口：登录切换、四端视图装配与定时任务驱动。"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk

from app.container import AppContext, build_context
from app.domain.enums import UserRole
from app.jobs.scheduler import Scheduler
from app.seed import seed_if_empty
from app.ui.admin import AdminView
from app.ui.customer import CustomerView
from app.ui.login import LoginView
from app.ui.merchant import MerchantView
from app.ui.rider import RiderView
from app.ui.theme import apply_theme

logger = logging.getLogger(__name__)


class MainApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.ctx: AppContext = build_context()
        if seed_if_empty(self.ctx):
            self.ctx.db.save()
        self.scheduler = Scheduler(self.ctx)
        self.session = None
        self.user = None
        self.current_view = None

        self.title("城市外卖点餐与配送平台 · 原型")
        self.geometry("1320x880")
        self.minsize(1120, 720)
        self.configure(background="#F5F6F8")
        apply_theme(self)

        self._build_shell()
        self.show_login()
        self.after(1500, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ #
    # 外壳
    # ------------------------------------------------------------------ #
    def _build_shell(self) -> None:
        self.header = ttk.Frame(self, style="Header.TFrame", padding=(22, 10))
        self.header.pack(fill="x")
        ttk.Label(self.header, text="城市外卖", style="Brand.TLabel").pack(side="left")
        ttk.Label(
            self.header, text="点餐与配送平台", style="CardMuted.TLabel"
        ).pack(side="left", padx=(8, 0))

        self.logout_button = ttk.Button(self.header, text="退出登录", command=self.logout)
        self.user_label = ttk.Label(self.header, text="", style="CardMuted.TLabel")
        self.badge_label = ttk.Label(self.header, text="", style="Muted.TLabel")

        self.container = ttk.Frame(self)
        self.container.pack(fill="both", expand=True, padx=14, pady=10)

        status_bar = ttk.Frame(self, padding=(20, 6))
        status_bar.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status_bar, textvariable=self.status_var, style="Muted.TLabel").pack(
            side="left"
        )
        self.clock_var = tk.StringVar()
        ttk.Label(status_bar, textvariable=self.clock_var, style="Muted.TLabel").pack(
            side="right"
        )

    # ------------------------------------------------------------------ #
    # 会话
    # ------------------------------------------------------------------ #
    def show_login(self) -> None:
        self.session = None
        self.user = None
        self.current_view = None
        self.user_label.pack_forget()
        self.badge_label.pack_forget()
        self.logout_button.pack_forget()
        self._clear_container()
        view = LoginView(self.container, self)
        view.pack(fill="both", expand=True)
        self.current_view = view
        self.status_var.set("请登录后使用")

    def on_login(self, session) -> None:
        self.session = session
        self.user = self.ctx.auth.current_user(session.token)
        self._clear_container()
        self.current_view = self._build_role_view()
        self.current_view.pack(fill="both", expand=True)

        self.user_label.configure(
            text=f"{self.user.nickname}　·　{self.user.role.label}"
        )
        self.user_label.pack(side="right", padx=(0, 12))
        self.badge_label.pack(side="right", padx=(0, 12))
        self.logout_button.pack(side="right")
        self.refresh_badge()
        self.status_var.set(f"欢迎，{self.user.nickname}")
        self.current_view.safe_refresh()

    def logout(self) -> None:
        if not messagebox.askyesno("退出登录", "确定要退出当前账号吗？", parent=self):
            return
        if self.session is not None:
            self.ctx.auth.logout(self.session.token)
        self.show_login()

    def _build_role_view(self):
        uid = self.user.user_id
        if self.user.role is UserRole.CUSTOMER:
            return CustomerView(self.container, self, uid)
        if self.user.role is UserRole.MERCHANT:
            return MerchantView(self.container, self, uid)
        if self.user.role is UserRole.RIDER:
            return RiderView(self.container, self, uid)
        return AdminView(self.container, self, uid)

    def _clear_container(self) -> None:
        for child in self.container.winfo_children():
            child.destroy()

    # ------------------------------------------------------------------ #
    # 通用
    # ------------------------------------------------------------------ #
    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def refresh_badge(self) -> None:
        if self.user is None:
            return
        unread = self.ctx.notifications.unread_count(self.user.user_id)
        self.badge_label.configure(text=f"未读消息 {unread}" if unread else "消息已读")

    def _tick(self) -> None:
        try:
            report = self.scheduler.tick()
            if report.changed:
                self.status_var.set(
                    "定时任务：取消 "
                    f"{report.cancelled_unpaid + report.cancelled_accept_timeout} 笔订单，"
                    f"自动退款 {report.refunds_auto_approved} 笔，"
                    f"派单升级 {report.dispatch_escalated} 笔，"
                    f"自动收货 {report.auto_completed} 笔"
                )
            if self.current_view is not None and self.session is not None:
                self.current_view.auto_refresh()
                self.refresh_badge()
            self.clock_var.set(self.ctx.stats.today().strftime("%Y-%m-%d"))
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            logger.exception("定时刷新失败")
        finally:
            self.after(2000, self._tick)

    def _on_close(self) -> None:
        try:
            self.ctx.db.save()
        finally:
            self.destroy()


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = MainApp()
    app.mainloop()
    return 0
