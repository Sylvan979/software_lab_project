"""平台管理端：经营看板、店铺审核、退款仲裁、调度与审计。"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from app.domain.enums import (
    AccountStatus,
    DeliveryStatus,
    ResponsibleParty,
    StoreStatus,
    UserRole,
)
from app.ui.base import BaseView, ModalDialog
from app.ui.dialogs import TextDialog
from app.ui.theme import FAINT, GREEN, MUTED, RED
from app.ui.widgets import (
    add_field,
    add_row,
    clear_tree,
    fmt_time,
    make_detail,
    make_table,
    selected_id,
    set_detail,
    status_tag,
)


class AdminView(BaseView):
    def __init__(self, master, app, user_id: str) -> None:
        super().__init__(master, app, user_id)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        self._build_dashboard_tab()
        self._build_store_tab()
        self._build_refund_tab()
        self._build_dispatch_tab()
        self._build_user_tab()
        self._build_audit_tab()
        self.notebook.bind("<<NotebookTabChanged>>", lambda _e: self.safe_refresh())

    # ================================================================== #
    # 看板
    # ================================================================== #
    def _build_dashboard_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="平台看板")

        self.metric_label = ttk.Label(tab, text="", style="H2.TLabel", justify="left")
        self.metric_label.pack(anchor="w", pady=(0, 4))
        self.metric_sub = ttk.Label(tab, text="", style="Muted.TLabel")
        self.metric_sub.pack(anchor="w", pady=(0, 12))

        panes = ttk.Panedwindow(tab, orient="horizontal")
        panes.pack(fill="both", expand=True)

        left = ttk.LabelFrame(panes, text="店铺营业额排名（已完成订单）", padding=8)
        panes.add(left, weight=2)
        frame, self.ranking_tree = make_table(
            left,
            [
                ("rank", "#", 40),
                ("store", "店铺", 180),
                ("orders", "完成单数", 80),
                ("revenue", "营业额", 100),
            ],
            height=14,
        )
        frame.pack(fill="both", expand=True)

        right = ttk.LabelFrame(panes, text="订单状态分布", padding=8)
        panes.add(right, weight=1)
        frame2, self.status_tree = make_table(
            right,
            [("status", "状态", 120), ("count", "数量", 70)],
            height=14,
        )
        frame2.pack(fill="both", expand=True)

    def _refresh_dashboard(self) -> None:
        stats = self.ctx.stats.platform_stats(self.user_id)
        self.metric_label.configure(
            text=(
                f"订单 {stats.total_orders} 笔　完成 {stats.completed_orders} 笔　"
                f"GMV ¥{stats.gmv:.2f}　退款 {stats.refund_orders} 笔"
            )
        )
        self.metric_sub.configure(
            text=(
                f"顾客 {stats.customers}　商家 {stats.merchants}　骑手 {stats.riders}　"
                f"营业中店铺 {stats.active_stores}"
            )
        )
        clear_tree(self.ranking_tree)
        for index, item in enumerate(stats.ranking, start=1):
            add_row(
                self.ranking_tree,
                item.store_id,
                (index, item.name, item.orders, f"¥{item.revenue:.2f}"),
            )
        clear_tree(self.status_tree)
        for label, count in self.ctx.stats.orders_by_status().items():
            add_row(self.status_tree, label, (label, count), tag=status_tag(label))

    # ================================================================== #
    # 店铺审核
    # ================================================================== #
    def _build_store_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="店铺审核")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="刷新", command=self.safe_refresh).pack(side="left")
        ttk.Button(
            toolbar, text="审核通过", style="Accent.TButton", command=self._approve_store
        ).pack(side="left", padx=6)
        ttk.Button(toolbar, text="驳回申请", command=self._reject_store).pack(side="left")
        ttk.Label(toolbar, text="待审核店铺：", style="Muted.TLabel").pack(side="left", padx=(16, 0))

        frame, self.pending_store_tree = make_table(
            tab,
            [
                ("id", "店铺号", 90),
                ("name", "店铺名称", 180),
                ("address", "地址", 220),
                ("merchant", "商家", 120),
                ("created", "申请时间", 100),
            ],
            height=6,
        )
        frame.pack(fill="both", expand=True)

        toolbar2 = ttk.Frame(tab)
        toolbar2.pack(fill="x", pady=(12, 8))
        ttk.Button(toolbar2, text="关停店铺", style="Danger.TButton", command=self._suspend_store).pack(
            side="left"
        )
        ttk.Button(toolbar2, text="解除关停", command=self._restore_store).pack(
            side="left", padx=6
        )
        ttk.Label(toolbar2, text="全部店铺：", style="Muted.TLabel").pack(side="left", padx=(16, 0))

        frame2, self.all_store_tree = make_table(
            tab,
            [
                ("id", "店铺号", 90),
                ("name", "店铺名称", 180),
                ("status", "状态", 90),
                ("rating", "评分", 60),
                ("min", "起送价", 70),
                ("accept", "接单时限", 80),
            ],
            height=8,
        )
        frame2.pack(fill="both", expand=True)

    def _refresh_stores(self) -> None:
        clear_tree(self.pending_store_tree)
        for store in self.ctx.stores.pending_stores(self.user_id):
            merchant = self.ctx.repos.users.get(store.merchant_id)
            add_row(
                self.pending_store_tree,
                store.store_id,
                (
                    store.store_id,
                    store.name,
                    store.address_text,
                    merchant.nickname,
                    fmt_time(store.created_at),
                ),
            )
        clear_tree(self.all_store_tree)
        for store in self.ctx.repos.stores.all():
            add_row(
                self.all_store_tree,
                store.store_id,
                (
                    store.store_id,
                    store.name,
                    store.status.label,
                    f"{store.rating:.2f}",
                    f"¥{store.min_order_amount:.2f}",
                    f"{store.accept_timeout_minutes} 分钟",
                ),
                tag="muted" if store.status is StoreStatus.SUSPENDED else None,
            )

    def _selected(self, tree, kind: str) -> str | None:
        item = selected_id(tree)
        if not item:
            messagebox.showinfo("提示", f"请先选择{kind}", parent=self)
        return item

    def _approve_store(self) -> None:
        store_id = self._selected(self.pending_store_tree, "待审核店铺")
        if store_id:
            self.guard(
                lambda: self.ctx.stores.approve_store(self.user_id, store_id),
                "店铺已通过审核",
            )

    def _reject_store(self) -> None:
        store_id = self._selected(self.pending_store_tree, "待审核店铺")
        if not store_id:
            return
        reason = TextDialog(self, "驳回入驻申请", "请输入驳回原因").show()
        if reason:
            self.guard(
                lambda: self.ctx.stores.reject_store(self.user_id, store_id, reason),
                "已驳回入驻申请",
            )

    def _suspend_store(self) -> None:
        store_id = self._selected(self.all_store_tree, "店铺")
        if not store_id:
            return
        reason = TextDialog(self, "关停店铺", "请输入关停原因").show()
        if reason:
            self.guard(
                lambda: self.ctx.stores.suspend_store(self.user_id, store_id, reason),
                "店铺已关停",
            )

    def _restore_store(self) -> None:
        store_id = self._selected(self.all_store_tree, "店铺")
        if store_id:
            self.guard(
                lambda: self.ctx.stores.restore_store(self.user_id, store_id),
                "已解除店铺关停",
            )

    # ================================================================== #
    # 退款仲裁
    # ================================================================== #
    def _build_refund_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="退款仲裁")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="刷新", command=self.safe_refresh).pack(side="left")
        ttk.Button(
            toolbar, text="仲裁处理", style="Accent.TButton", command=self._arbitrate
        ).pack(side="left", padx=6)
        ttk.Label(
            toolbar,
            text="商家超时未处理时由平台判定责任方并给出结论",
            style="Muted.TLabel",
        ).pack(side="left", padx=12)

        self.refund_frame, self.refund_tree = make_table(
            tab,
            [
                ("id", "退款单", 90),
                ("order", "订单号", 100),
                ("store", "店铺", 150),
                ("amount", "金额", 70),
                ("reason", "申请原因", 200),
                ("deadline", "商家处理截止", 100),
            ],
            height=12,
        )
        self.refund_frame.pack(fill="both", expand=True)
        self.refund_tree.bind("<<TreeviewSelect>>", lambda _e: self._show_refund())

        ttk.Label(tab, text="退款详情", style="Muted.TLabel").pack(anchor="w", pady=(8, 2))
        self.refund_detail = make_detail(tab, height=8)
        self.refund_detail.pack(fill="both", expand=True)

    def _refresh_refunds(self) -> None:
        selected = selected_id(self.refund_tree)
        clear_tree(self.refund_tree)
        for refund in self.ctx.refunds.all_pending(self.user_id):
            store = self.ctx.repos.stores.get(refund.store_id)
            add_row(
                self.refund_tree,
                refund.refund_id,
                (
                    refund.refund_id,
                    refund.order_id,
                    store.name,
                    f"¥{refund.amount:.2f}",
                    refund.reason,
                    fmt_time(refund.deadline),
                ),
            )
        if selected and self.refund_tree.exists(selected):
            self.refund_tree.selection_set(selected)
        elif self.refund_tree.get_children():
            self.refund_tree.selection_set(self.refund_tree.get_children()[0])
        self._show_refund()

    def _show_refund(self) -> None:
        refund_id = selected_id(self.refund_tree)
        if not refund_id:
            set_detail(self.refund_detail, "暂无待处理退款")
            return
        refund = self.ctx.repos.refunds.get(refund_id)
        order = self.ctx.repos.orders.get(refund.order_id)
        store = self.ctx.repos.stores.get(refund.store_id)
        lines = [
            f"退款单 {refund.refund_id}　状态：{refund.status.label}",
            f"订单 {order.order_id}　店铺：{store.name}",
            f"金额 ¥{refund.amount:.2f}　申请时间 {refund.created_at:%Y-%m-%d %H:%M}",
            f"申请原因：{refund.reason}",
            f"订单当前状态：{order.status.label}",
            "",
            "商品明细：",
        ]
        for item in order.items:
            lines.append(f"  {item.dish_name} × {item.quantity}　¥{item.subtotal:.2f}")
        set_detail(self.refund_detail, "\n".join(lines))

    def _arbitrate(self) -> None:
        refund_id = self._selected(self.refund_tree, "退款单")
        if not refund_id:
            return
        result = ArbitrationDialog(self).show()
        if result is None:
            return
        approve, party, conclusion = result
        self.guard(
            lambda: self.ctx.refunds.admin_arbitrate(
                refund_id,
                self.user_id,
                approve=approve,
                responsible_party=party,
                conclusion=conclusion,
            ),
            "仲裁完成：支持退款" if approve else "仲裁完成：驳回退款",
        )

    # ================================================================== #
    # 配送调度
    # ================================================================== #
    def _build_dispatch_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="配送调度")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="刷新", command=self.safe_refresh).pack(side="left")
        ttk.Label(toolbar, text="指派骑手", style="Muted.TLabel").pack(side="left", padx=(16, 4))
        self.rider_combo = ttk.Combobox(toolbar, state="readonly", width=24)
        self.rider_combo.pack(side="left")
        ttk.Button(
            toolbar, text="重新派单", style="Accent.TButton", command=self._redispatch
        ).pack(side="left", padx=8)
        ttk.Label(
            toolbar, text="仅在线且未满 3 单的骑手可被指派", style="Muted.TLabel"
        ).pack(side="left", padx=8)

        frame, self.failed_tree = make_table(
            tab,
            [
                ("task", "原配送单", 100),
                ("order", "订单号", 100),
                ("store", "店铺", 150),
                ("reason", "失败原因", 140),
                ("customer", "顾客", 110),
                ("fee", "运费", 70),
            ],
            height=13,
        )
        frame.pack(fill="both", expand=True)

    def _refresh_dispatch(self) -> None:
        clear_tree(self.failed_tree)
        for task, order in self.ctx.delivery.orders_for_admin():
            store = self.ctx.repos.stores.get(order.store_id)
            customer = self.ctx.repos.users.get(order.customer_id)
            add_row(
                self.failed_tree,
                order.order_id,
                (
                    task.task_id,
                    order.order_id,
                    store.name,
                    task.exception_reason or task.status.label,
                    customer.nickname,
                    f"¥{task.fee:.2f}",
                ),
                tag="refund",
            )
        riders = [
            rider
            for rider in self.ctx.repos.users.riders()
            if rider.online
            and len(rider.active_task_ids) < self.ctx.settings.max_rider_active_tasks
        ]
        choices = [
            f"{rider.nickname}（{rider.user_id}，进行中 {len(rider.active_task_ids)} 单）"
            for rider in riders
        ]
        current = self.rider_combo.get()
        self.rider_combo.configure(values=choices)
        if current in choices:
            self.rider_combo.set(current)
        elif choices:
            self.rider_combo.set(choices[0])
        else:
            self.rider_combo.set("")
        self._dispatch_riders = {choice: rider.user_id for choice, rider in zip(choices, riders)}

    def _redispatch(self) -> None:
        order_id = self._selected(self.failed_tree, "配送失败订单")
        if not order_id:
            return
        rider_id = getattr(self, "_dispatch_riders", {}).get(self.rider_combo.get())
        if not rider_id:
            messagebox.showinfo("提示", "当前没有可指派的在线骑手", parent=self)
            return
        self.guard(
            lambda: self.ctx.delivery.redispatch(order_id, self.user_id, rider_id),
            "已重新派单",
        )

    # ================================================================== #
    # 用户管理
    # ================================================================== #
    def _build_user_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="用户管理")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="刷新", command=self.safe_refresh).pack(side="left")
        ttk.Label(toolbar, text="角色筛选", style="Muted.TLabel").pack(side="left", padx=(16, 4))
        self.role_filter = ttk.Combobox(
            toolbar,
            state="readonly",
            width=14,
            values=["全部", *(role.label for role in UserRole)],
        )
        self.role_filter.set("全部")
        self.role_filter.pack(side="left")
        self.role_filter.bind("<<ComboboxSelected>>", lambda _e: self.safe_refresh())
        ttk.Button(
            toolbar, text="冻结账号", style="Danger.TButton", command=self._freeze
        ).pack(side="left", padx=(16, 6))
        ttk.Button(toolbar, text="解除冻结", command=self._unfreeze).pack(side="left")

        frame, self.user_tree = make_table(
            tab,
            [
                ("id", "用户号", 100),
                ("nickname", "昵称", 140),
                ("phone", "手机号", 120),
                ("role", "角色", 90),
                ("status", "状态", 80),
                ("rider", "在线/完成", 100),
                ("created", "注册时间", 100),
            ],
            height=15,
        )
        frame.pack(fill="both", expand=True)

    def _refresh_users(self) -> None:
        role = None
        if self.role_filter.get() != "全部":
            role = next(r for r in UserRole if r.label == self.role_filter.get())
        clear_tree(self.user_tree)
        for user in self.ctx.users.list_users(self.user_id, role=role):
            rider_extra = "-"
            if user.role is UserRole.RIDER:
                rider_extra = f"{'在线' if user.online else '离线'} / {user.completed_count}"
            add_row(
                self.user_tree,
                user.user_id,
                (
                    user.user_id,
                    user.nickname,
                    user.phone,
                    user.role.label,
                    user.status.label,
                    rider_extra,
                    fmt_time(user.created_at),
                ),
                tag="muted" if user.status is AccountStatus.FROZEN else None,
            )

    def _freeze(self) -> None:
        user_id = self._selected(self.user_tree, "用户")
        if not user_id:
            return
        reason = TextDialog(self, "冻结账号", "请输入冻结原因").show()
        if reason:
            self.guard(
                lambda: self.ctx.users.freeze_user(self.user_id, user_id, reason),
                "账号已冻结",
            )

    def _unfreeze(self) -> None:
        user_id = self._selected(self.user_tree, "用户")
        if user_id:
            self.guard(
                lambda: self.ctx.users.unfreeze_user(self.user_id, user_id),
                "账号已恢复",
            )

    # ================================================================== #
    # 审计日志
    # ================================================================== #
    def _build_audit_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="审计日志")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="刷新", command=self.safe_refresh).pack(side="left")
        ttk.Label(toolbar, text="操作者/对象编号", style="Muted.TLabel").pack(
            side="left", padx=(16, 4)
        )
        self.audit_keyword = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.audit_keyword, width=18).pack(side="left")
        ttk.Button(toolbar, text="查询", command=self.safe_refresh).pack(side="left", padx=6)
        ttk.Label(toolbar, text="日志只追加，不可修改或删除", style="Muted.TLabel").pack(
            side="left", padx=12
        )

        frame, self.audit_tree = make_table(
            tab,
            [
                ("time", "时间", 130),
                ("actor", "操作者", 130),
                ("role", "角色", 90),
                ("action", "动作", 140),
                ("target", "对象", 140),
                ("detail", "详情", 300),
                ("result", "结果", 60),
            ],
            height=16,
        )
        frame.pack(fill="both", expand=True)

    def _refresh_audit(self) -> None:
        keyword = self.audit_keyword.get().strip()
        logs = self.ctx.audit.query(limit=500)
        if keyword:
            logs = [
                log
                for log in logs
                if keyword in log.actor_id or keyword in log.target_id
            ]
        clear_tree(self.audit_tree)
        for log in logs[:300]:
            add_row(
                self.audit_tree,
                log.log_id,
                (
                    log.created_at.strftime("%m-%d %H:%M:%S"),
                    log.actor_id,
                    log.actor_role,
                    log.action,
                    f"{log.target_type} {log.target_id}",
                    log.detail,
                    log.result,
                ),
            )

    # ================================================================== #
    def refresh(self) -> None:
        self._refresh_dashboard()
        self._refresh_stores()
        self._refresh_refunds()
        self._refresh_dispatch()
        self._refresh_users()
        self._refresh_audit()


class ArbitrationDialog(ModalDialog):
    """平台仲裁：是否退款、责任方、仲裁结论。"""

    def __init__(self, parent) -> None:
        super().__init__(parent, "退款仲裁")
        self.approve_var = tk.StringVar(value="approve")
        self.party_var = tk.StringVar(value=ResponsibleParty.MERCHANT.label)
        self.conclusion_var = tk.StringVar()

        ttk.Label(self.body, text="处理结论", style="Muted.TLabel").pack(anchor="w")
        row = ttk.Frame(self.body)
        row.pack(anchor="w", pady=(2, 10))
        ttk.Radiobutton(
            row, text="支持退款", variable=self.approve_var, value="approve"
        ).pack(side="left")
        ttk.Radiobutton(
            row, text="驳回退款", variable=self.approve_var, value="reject"
        ).pack(side="left", padx=12)

        ttk.Label(self.body, text="责任方", style="Muted.TLabel").pack(anchor="w")
        ttk.Combobox(
            self.body,
            textvariable=self.party_var,
            values=[p.label for p in ResponsibleParty],
            state="readonly",
            width=24,
        ).pack(anchor="w", pady=(2, 10))

        ttk.Label(self.body, text="仲裁结论", style="Muted.TLabel").pack(anchor="w")
        self.conclusion_entry = ttk.Entry(self.body, textvariable=self.conclusion_var, width=44)
        self.conclusion_entry.pack(anchor="w", pady=(2, 12))

        ttk.Button(
            self.body, text="提交仲裁", style="Accent.TButton", command=self._submit
        ).pack(anchor="e")

    def _submit(self) -> None:
        conclusion = self.conclusion_var.get().strip()
        if not conclusion:
            messagebox.showinfo("提示", "请填写仲裁结论", parent=self)
            return
        party = next(p for p in ResponsibleParty if p.label == self.party_var.get())
        self.result = (self.approve_var.get() == "approve", party, conclusion)
        self.destroy()
