"""骑手端：上线接单、配送任务与异常上报。"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from app.domain.enums import DeliveryStatus
from app.services.delivery import EXCEPTION_REASONS
from app.services.privacy import mask_detail
from app.ui.base import BaseView
from app.ui.dialogs import ChoiceDialog
from app.ui.theme import FAINT, GREEN
from app.ui.widgets import (
    add_row,
    clear_tree,
    fmt_time,
    make_detail,
    make_table,
    selected_id,
    set_detail,
)


class RiderView(BaseView):
    def __init__(self, master, app, user_id: str) -> None:
        super().__init__(master, app, user_id)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        self._build_hall_tab()
        self._build_mytask_tab()
        self._build_message_tab()
        self.notebook.bind("<<NotebookTabChanged>>", lambda _e: self.safe_refresh())

    # ================================================================== #
    # 接单大厅
    # ================================================================== #
    def _build_hall_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="接单大厅")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 8))
        self.online_label = ttk.Label(toolbar, text="", style="Muted.TLabel")
        self.online_label.pack(side="left", padx=(0, 12))
        self.online_button = ttk.Button(
            toolbar, text="上线接单", style="Accent.TButton", command=self._toggle_online
        )
        self.online_button.pack(side="left")
        ttk.Button(toolbar, text="刷新", command=self.safe_refresh).pack(side="left", padx=8)
        ttk.Label(
            toolbar,
            text="按距离由近及远排列；取餐前送达地址仅显示到楼栋",
            style="Muted.TLabel",
        ).pack(side="left", padx=12)

        self.hall_frame, self.hall_tree = make_table(
            tab,
            [
                ("task", "配送单", 100),
                ("store", "取餐门店", 160),
                ("pickup", "取餐地址", 220),
                ("dropoff", "送达地址", 200),
                ("distance", "距离", 70),
                ("fee", "运费", 70),
                ("deadline", "抢单截止", 100),
            ],
            height=13,
        )
        self.hall_frame.pack(fill="both", expand=True)

        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(
            actions, text="抢单", style="Accent.TButton", command=self._grab
        ).pack(side="left")
        ttk.Label(
            actions,
            text="上线后才能抢单；同时最多 3 单，超时将转人工调度",
            style="Muted.TLabel",
        ).pack(side="left", padx=12)

    # ================================================================== #
    # 我的配送
    # ================================================================== #
    def _build_mytask_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="我的配送")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="刷新", command=self.safe_refresh).pack(side="left")
        ttk.Button(
            toolbar, text="确认取餐", style="Accent.TButton", command=self._pickup
        ).pack(side="left", padx=6)
        ttk.Button(toolbar, text="确认送达", command=self._deliver).pack(side="left")
        ttk.Button(
            toolbar, text="上报异常", style="Danger.TButton", command=self._report
        ).pack(side="left", padx=6)

        self.mine_frame, self.mine_tree = make_table(
            tab,
            [
                ("task", "配送单", 100),
                ("order", "订单号", 110),
                ("status", "状态", 80),
                ("store", "门店", 150),
                ("distance", "距离", 70),
                ("fee", "运费", 70),
                ("created", "接单时间", 100),
            ],
            height=8,
        )
        self.mine_frame.pack(fill="both", expand=True)
        self.mine_tree.bind("<<TreeviewSelect>>", lambda _e: self._show_task())

        ttk.Label(tab, text="配送详情（取餐后显示完整门牌与电话）", style="Muted.TLabel").pack(
            anchor="w", pady=(8, 2)
        )
        self.task_detail = make_detail(tab, height=10)
        self.task_detail.pack(fill="both", expand=True)

    # ================================================================== #
    # 消息
    # ================================================================== #
    def _build_message_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="消息")
        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="刷新", command=self.safe_refresh).pack(side="left")
        ttk.Button(toolbar, text="全部标为已读", command=self._mark_all_read).pack(
            side="left", padx=6
        )
        self.msg_frame, self.msg_tree = make_table(
            tab,
            [
                ("time", "时间", 110),
                ("title", "标题", 160),
                ("body", "内容", 480),
                ("read", "状态", 60),
            ],
            height=15,
        )
        self.msg_frame.pack(fill="both", expand=True)

    # ================================================================== #
    # 操作
    # ================================================================== #
    def _rider(self):
        return self.ctx.repos.users.get(self.user_id)

    def _toggle_online(self) -> None:
        rider = self._rider()
        self.guard(
            lambda: self.ctx.delivery.set_online(self.user_id, not rider.online),
            "已上线，可以开始抢单" if not rider.online else "已下线",
        )

    def _grab(self) -> None:
        task_id = selected_id(self.hall_tree)
        if not task_id:
            messagebox.showinfo("提示", "请先选择配送单", parent=self)
            return
        self.guard(
            lambda: self.ctx.delivery.grab(task_id, self.user_id),
            "抢单成功，请尽快到店取餐",
        )

    def _selected_mine(self) -> str | None:
        task_id = selected_id(self.mine_tree)
        if not task_id:
            messagebox.showinfo("提示", "请先在“我的配送”中选择任务", parent=self)
        return task_id

    def _pickup(self) -> None:
        task_id = self._selected_mine()
        if task_id:
            self.guard(
                lambda: self.ctx.delivery.pickup(task_id, self.user_id),
                "已确认取餐，正在配送",
            )

    def _deliver(self) -> None:
        task_id = self._selected_mine()
        if task_id:
            self.guard(
                lambda: self.ctx.delivery.deliver(task_id, self.user_id),
                "已确认送达",
            )

    def _report(self) -> None:
        task_id = self._selected_mine()
        if not task_id:
            return
        reason = ChoiceDialog(
            self, "上报配送异常", list(EXCEPTION_REASONS), "请选择异常原因"
        ).show()
        if reason:
            self.guard(
                lambda: self.ctx.delivery.report_exception(task_id, self.user_id, reason),
                "异常已上报，平台将介入处理",
            )

    def _mark_all_read(self) -> None:
        self.ctx.notifications.mark_all_read(self.user_id)
        self.safe_refresh()
        self.app.refresh_badge()

    # ================================================================== #
    # 刷新
    # ================================================================== #
    def refresh(self) -> None:
        rider = self._rider()
        color = GREEN if rider.online else FAINT
        self.online_label.configure(
            text=f"● {'在线' if rider.online else '离线'}　进行中 {len(rider.active_task_ids)} 单",
            foreground=color,
        )
        self.online_button.configure(text="下线休息" if rider.online else "上线接单")

        hall_selected = selected_id(self.hall_tree)
        clear_tree(self.hall_tree)
        for task in self.ctx.delivery.available_tasks():
            order = self.ctx.repos.orders.get(task.order_id)
            store = self.ctx.repos.stores.get(task.store_id)
            add_row(
                self.hall_tree,
                task.task_id,
                (
                    task.task_id,
                    store.name,
                    task.pickup_text,
                    mask_detail(order.address.detail, reveal=False),
                    f"{task.distance_km:.2f} km",
                    f"¥{task.fee:.2f}",
                    fmt_time(task.deadline),
                ),
            )
        if hall_selected and self.hall_tree.exists(hall_selected):
            self.hall_tree.selection_set(hall_selected)

        mine_selected = selected_id(self.mine_tree)
        clear_tree(self.mine_tree)
        for task in self.ctx.delivery.my_tasks(self.user_id):
            store = self.ctx.repos.stores.get(task.store_id)
            add_row(
                self.mine_tree,
                task.task_id,
                (
                    task.task_id,
                    task.order_id,
                    task.status.label,
                    store.name,
                    f"{task.distance_km:.2f} km",
                    f"¥{task.fee:.2f}",
                    fmt_time(task.grabbed_at),
                ),
            )
        if mine_selected and self.mine_tree.exists(mine_selected):
            self.mine_tree.selection_set(mine_selected)
        elif self.mine_tree.get_children():
            self.mine_tree.selection_set(self.mine_tree.get_children()[0])
        self._show_task()

        clear_tree(self.msg_tree)
        for note in self.ctx.notifications.list_for(self.user_id):
            add_row(
                self.msg_tree,
                note.notification_id,
                (fmt_time(note.created_at), note.title, note.body, "已读" if note.read else "未读"),
                tag=None if note.read else "done",
            )

    def _show_task(self) -> None:
        task_id = selected_id(self.mine_tree)
        if not task_id:
            set_detail(self.task_detail, "暂无进行中的配送任务")
            return
        view = self.ctx.delivery.rider_view(task_id, self.user_id)
        task, order = self.ctx.delivery.task_detail(task_id)
        lines = [
            f"配送单 {view['task_id']}　状态：{task.status.label}",
            f"订单号 {view['order_id']}　距离 {view['distance']}　运费 {view['fee']}",
            f"取餐门店：{view['store']}",
            f"取餐地址：{view['pickup']}",
            f"送达地址：{view['dropoff']}",
            f"收货人：{view['receiver']}　电话：{view['phone']}",
            f"订单状态：{order.status.label}",
        ]
        if task.status is DeliveryStatus.GRABBED:
            lines.append("请到店确认取餐后再前往送达地址")
        if task.exception_reason:
            lines.append(f"异常原因：{task.exception_reason}")
        set_detail(self.task_detail, "\n".join(lines))
