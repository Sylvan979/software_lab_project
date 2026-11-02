"""商家端：店铺经营、菜品库存、订单处理与退款。"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from app.domain.enums import DishStatus, OrderStatus, StoreStatus
from app.services.orders import REJECT_REASONS
from app.services.privacy import mask_detail, mask_phone
from app.ui.base import BaseView, ModalDialog
from app.ui.dialogs import ChoiceDialog
from app.ui.panels import MessagePanel
from app.ui.theme import FAINT, GREEN, RED
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


class MerchantView(BaseView):
    def __init__(self, master, app, user_id: str) -> None:
        super().__init__(master, app, user_id)
        self.store = self.ctx.stores.store_of_merchant(user_id)
        self._loaded_store_id: str | None = None
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        self._build_store_tab()
        self._build_dish_tab()
        self._build_order_tab()
        self._build_refund_tab()
        self._build_message_tab()
        self.notebook.bind("<<NotebookTabChanged>>", lambda _e: self.safe_refresh())

    # ================================================================== #
    # 店铺
    # ================================================================== #
    def _build_store_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="店铺经营")
        self.store_tab = tab

        self.apply_frame = ttk.LabelFrame(tab, text="入驻申请（首次登录需先创建店铺）", padding=14)
        self.reg_name = tk.StringVar(value="我的小店")
        self.reg_desc = tk.StringVar(value="现做现卖")
        self.reg_address = tk.StringVar(value="学府路 20 号")
        self.reg_x = tk.StringVar(value="0.5")
        self.reg_y = tk.StringVar(value="0.5")
        self.reg_min = tk.StringVar(value="15")
        add_field(self.apply_frame, 0, 0, "店铺名称", self.reg_name)
        add_field(self.apply_frame, 1, 0, "店铺简介", self.reg_desc, width=30)
        add_field(self.apply_frame, 2, 0, "门店地址", self.reg_address, width=30)
        add_field(self.apply_frame, 3, 0, "坐标 x", self.reg_x, width=8)
        add_field(self.apply_frame, 3, 2, "坐标 y", self.reg_y, width=8)
        add_field(self.apply_frame, 4, 0, "起送价", self.reg_min, width=8)
        ttk.Button(
            self.apply_frame,
            text="提交入驻申请",
            style="Accent.TButton",
            command=self._apply_store,
        ).grid(row=5, column=0, sticky="w", pady=(12, 0))

        self.manage_frame = ttk.Frame(tab)
        self.store_title = ttk.Label(self.manage_frame, text="", style="H2.TLabel")
        self.store_title.grid(row=0, column=0, sticky="w")
        self.store_status_label = ttk.Label(self.manage_frame, text="", style="Muted.TLabel")
        self.store_status_label.grid(row=0, column=1, sticky="w", padx=12)

        self.stats_label = ttk.Label(
            self.manage_frame, text="", style="Muted.TLabel", justify="left"
        )
        self.stats_label.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 12))

        buttons = ttk.Frame(self.manage_frame)
        buttons.grid(row=2, column=0, columnspan=4, sticky="w")
        self.business_button = ttk.Button(
            buttons, text="切换营业状态", style="Accent.TButton", command=self._toggle_business
        )
        self.business_button.pack(side="left")
        ttk.Button(buttons, text="刷新", command=self.safe_refresh).pack(side="left", padx=8)

        form = ttk.LabelFrame(self.manage_frame, text="店铺设置", padding=12)
        form.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(16, 0))
        self.notice_var = tk.StringVar()
        self.min_order_var = tk.StringVar()
        self.accept_timeout_var = tk.StringVar()
        add_field(form, 0, 0, "公告", self.notice_var, width=40)
        add_field(form, 1, 0, "起送价", self.min_order_var, width=8)
        add_field(form, 1, 2, "接单时限（5-20 分钟）", self.accept_timeout_var, width=8)
        ttk.Button(form, text="保存设置", command=self._save_store).grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )

    def _apply_store(self) -> None:
        store = self.guard(
            lambda: self.ctx.stores.apply_store(
                self.user_id,
                name=self.reg_name.get(),
                description=self.reg_desc.get(),
                address_text=self.reg_address.get(),
                x_km=float(self.reg_x.get() or 0),
                y_km=float(self.reg_y.get() or 0),
                min_order_amount=self.reg_min.get(),
            ),
            "入驻申请已提交，等待平台审核",
        )
        if store:
            self.store = store
            self.safe_refresh()

    def _toggle_business(self) -> None:
        if self.store is None:
            return
        target = not self.store.is_open
        self.guard(
            lambda: self.ctx.stores.set_business_status(self.user_id, target),
            "已开始营业" if target else "已切换为休息中",
        )

    def _save_store(self) -> None:
        self.guard(
            lambda: self.ctx.stores.update_store(
                self.user_id,
                notice=self.notice_var.get(),
                min_order_amount=self.min_order_var.get(),
                accept_timeout_minutes=int(self.accept_timeout_var.get() or 10),
            ),
            "店铺设置已保存",
        )

    def _refresh_store_tab(self) -> None:
        self.store = self.ctx.stores.store_of_merchant(self.user_id)
        has_store = self.store is not None
        if has_store:
            self.apply_frame.pack_forget()
            self.manage_frame.pack(fill="both", expand=True)
        else:
            self.manage_frame.pack_forget()
            self.apply_frame.pack(fill="x")
            return

        store = self.store
        assert store is not None
        self.store_title.configure(text=store.name)
        color = GREEN if store.is_open else FAINT
        if store.status is StoreStatus.SUSPENDED:
            color = RED
        self.store_status_label.configure(text=f"● {store.status.label}", foreground=color)
        locked = store.status in (StoreStatus.PENDING, StoreStatus.SUSPENDED)
        self.business_button.configure(
            text="休息一下" if store.is_open else "开始营业",
            state="disabled" if locked else "normal",
        )
        stats = self.ctx.stats.merchant_stats(self.user_id, day=self.ctx.stats.today())
        self.stats_label.configure(
            text=(
                f"今日订单 {stats.order_count} 笔　完成 {stats.completed_count} 笔　"
                f"营业额 ¥{stats.revenue:.2f}　退款 {stats.refund_count} 笔　"
                f"超时未接单 {stats.timeout_count} 次　评分 {stats.rating:.2f}"
            )
        )
        if self._loaded_store_id != store.store_id:
            self._loaded_store_id = store.store_id
            self.notice_var.set(store.notice)
            self.min_order_var.set(f"{store.min_order_amount:.2f}")
            self.accept_timeout_var.set(str(store.accept_timeout_minutes))

    # ================================================================== #
    # 菜品
    # ================================================================== #
    def _build_dish_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="菜品与库存")

        top = ttk.Frame(tab)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="分类", style="Muted.TLabel").pack(side="left")
        self.category_combo = ttk.Combobox(top, state="readonly", width=16)
        self.category_combo.pack(side="left", padx=6)
        self.new_category = tk.StringVar()
        ttk.Entry(top, textvariable=self.new_category, width=14).pack(side="left", padx=(8, 4))
        ttk.Button(top, text="新增分类", command=self._add_category).pack(side="left")
        ttk.Label(top, text="已下架菜品不参与库存自动变更", style="Muted.TLabel").pack(
            side="left", padx=12
        )

        self.dish_frame, self.dish_tree = make_table(
            tab,
            [
                ("category", "分类", 90),
                ("name", "菜品", 150),
                ("price", "价格", 70),
                ("stock", "库存", 60),
                ("sales", "月售", 60),
                ("status", "状态", 80),
                ("desc", "说明", 220),
            ],
            height=10,
        )
        self.dish_frame.pack(fill="both", expand=True)

        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=(8, 0))
        for text, command in (
            ("修改菜品", self._edit_dish),
            ("上架", lambda: self._set_dish_status(DishStatus.ON_SALE)),
            ("下架", lambda: self._set_dish_status(DishStatus.OFF_SHELF)),
        ):
            ttk.Button(actions, text=text, command=command).pack(side="left", padx=4)

        form = ttk.LabelFrame(tab, text="新增菜品", padding=12)
        form.pack(fill="x", pady=(12, 0))
        self.dish_name = tk.StringVar()
        self.dish_price = tk.StringVar()
        self.dish_stock = tk.StringVar(value="20")
        self.dish_desc = tk.StringVar()
        add_field(form, 0, 0, "名称", self.dish_name)
        add_field(form, 0, 2, "价格", self.dish_price, width=8)
        add_field(form, 0, 4, "库存", self.dish_stock, width=8)
        add_field(form, 1, 0, "说明", self.dish_desc, width=36)
        ttk.Button(form, text="添加菜品", style="Accent.TButton", command=self._add_dish).grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )

    def _refresh_dishes(self) -> None:
        if self.store is None:
            clear_tree(self.dish_tree)
            self.category_combo.configure(values=[])
            return
        categories = self.ctx.repos.categories.by_store(self.store.store_id)
        current = self.category_combo.get()
        values = [c.name for c in categories]
        self.category_combo.configure(values=values)
        if current in values:
            self.category_combo.set(current)
        elif values:
            self.category_combo.set(values[0])
        else:
            self.category_combo.set("")

        category_names = {c.category_id: c.name for c in categories}
        selected = selected_id(self.dish_tree)
        clear_tree(self.dish_tree)
        for dish in self.ctx.stores.dishes_of_store(self.store.store_id):
            add_row(
                self.dish_tree,
                dish.dish_id,
                (
                    category_names.get(dish.category_id, "未分类"),
                    dish.name,
                    f"¥{dish.price:.2f}",
                    dish.stock,
                    dish.monthly_sales,
                    dish.status.label,
                    dish.description or "-",
                ),
                tag=None if dish.is_available else "muted",
            )
        if selected and self.dish_tree.exists(selected):
            self.dish_tree.selection_set(selected)

    def _add_category(self) -> None:
        name = self.new_category.get().strip()
        if not name:
            return
        category = self.guard(
            lambda: self.ctx.stores.add_category(self.user_id, name), "分类已创建"
        )
        if category:
            self.new_category.set("")
            self.safe_refresh()

    def _category_id(self) -> str | None:
        name = self.category_combo.get()
        if not name or self.store is None:
            return None
        for category in self.ctx.repos.categories.by_store(self.store.store_id):
            if category.name == name:
                return category.category_id
        return None

    def _add_dish(self) -> None:
        category_id = self._category_id()
        if not category_id:
            messagebox.showinfo("提示", "请先选择或新增分类", parent=self)
            return
        self.guard(
            lambda: self.ctx.stores.add_dish(
                self.user_id,
                category_id=category_id,
                name=self.dish_name.get(),
                price=self.dish_price.get(),
                stock=int(self.dish_stock.get() or 0),
                description=self.dish_desc.get(),
            ),
            "菜品已添加",
        )

    def _edit_dish(self) -> None:
        dish_id = selected_id(self.dish_tree)
        if not dish_id:
            return
        dialog = EditDishDialog(self, self.ctx, self.user_id, dish_id)
        if dialog.show():
            self.safe_refresh()

    def _set_dish_status(self, status: DishStatus) -> None:
        dish_id = selected_id(self.dish_tree)
        if not dish_id:
            return
        self.guard(
            lambda: self.ctx.stores.set_dish_status(self.user_id, dish_id, status),
            f"菜品已{status.label}",
        )

    # ================================================================== #
    # 订单
    # ================================================================== #
    def _build_order_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="订单处理")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="刷新", command=self.safe_refresh).pack(side="left")
        ttk.Button(toolbar, text="接单", style="Accent.TButton", command=self._accept).pack(
            side="left", padx=6
        )
        ttk.Button(toolbar, text="拒单", command=self._reject).pack(side="left")
        ttk.Button(toolbar, text="标记出餐", command=self._mark_ready).pack(side="left", padx=6)
        ttk.Label(
            toolbar,
            text="接单时限内未处理将被系统自动取消并退款",
            style="Muted.TLabel",
        ).pack(side="left", padx=12)

        self.merchant_order_frame, self.merchant_order_tree = make_table(
            tab,
            [
                ("id", "订单号", 110),
                ("status", "状态", 80),
                ("amount", "金额", 80),
                ("items", "商品", 240),
                ("created", "下单时间", 100),
            ],
            height=9,
        )
        self.merchant_order_frame.pack(fill="both", expand=True)
        self.merchant_order_tree.bind("<<TreeviewSelect>>", lambda _e: self._show_order())

        ttk.Label(tab, text="订单详情（顾客手机号与门牌已脱敏）", style="Muted.TLabel").pack(
            anchor="w", pady=(8, 2)
        )
        self.merchant_order_detail = make_detail(tab, height=9)
        self.merchant_order_detail.pack(fill="both", expand=True)

    def _refresh_orders(self) -> None:
        if self.store is None:
            clear_tree(self.merchant_order_tree)
            return
        selected = selected_id(self.merchant_order_tree)
        clear_tree(self.merchant_order_tree)
        for order in self.ctx.orders.list_for_store(self.user_id):
            items = "、".join(f"{i.dish_name}×{i.quantity}" for i in order.items)
            add_row(
                self.merchant_order_tree,
                order.order_id,
                (
                    order.order_id,
                    order.status.label,
                    f"¥{order.payable_amount:.2f}",
                    items,
                    fmt_time(order.created_at),
                ),
                tag=status_tag(order.status.label),
            )
        if selected and self.merchant_order_tree.exists(selected):
            self.merchant_order_tree.selection_set(selected)
        elif self.merchant_order_tree.get_children():
            self.merchant_order_tree.selection_set(
                self.merchant_order_tree.get_children()[0]
            )
        self._show_order()

    def _current_order(self):
        order_id = selected_id(self.merchant_order_tree)
        if not order_id:
            messagebox.showinfo("提示", "请先选择订单", parent=self)
            return None
        return self.ctx.repos.orders.get(order_id)

    def _show_order(self) -> None:
        order_id = selected_id(self.merchant_order_tree)
        if not order_id:
            set_detail(self.merchant_order_detail, "")
            return
        order = self.ctx.repos.orders.get(order_id)
        lines = [
            f"订单 {order.order_id}　状态：{order.status.label}",
            f"顾客：{mask_detail(order.address.receiver, reveal=False)}　"
            f"电话：{mask_phone(order.address.phone)}",
            f"送达地址：{mask_detail(order.address.detail, reveal=False)}",
            f"备注：{order.remark or '无'}",
            "",
        ]
        for item in order.items:
            lines.append(f"{item.dish_name} × {item.quantity}　¥{item.subtotal:.2f}")
        lines.append(f"实付 ¥{order.payable_amount:.2f}（含配送费 ¥{order.delivery_fee:.2f}）")
        if order.accept_deadline and order.status is OrderStatus.PENDING_ACCEPTANCE:
            lines.append(f"请在 {order.accept_deadline:%H:%M:%S} 前处理")
        refund = self.ctx.refunds.for_order(order.order_id)
        if refund:
            lines.append(f"退款：{refund.status.label}　{refund.reason}")
        set_detail(self.merchant_order_detail, "\n".join(lines))

    def _accept(self) -> None:
        order = self._current_order()
        if order:
            self.guard(
                lambda: self.ctx.orders.merchant_accept(order.order_id, self.user_id),
                "已接单",
            )

    def _reject(self) -> None:
        order = self._current_order()
        if order is None:
            return
        dialog = ChoiceDialog(self, "拒单原因", list(REJECT_REASONS), "请选择拒单原因")
        reason = dialog.show()
        if reason:
            self.guard(
                lambda: self.ctx.orders.merchant_reject(order.order_id, self.user_id, reason),
                "已拒单并全额退款",
            )

    def _mark_ready(self) -> None:
        order = self._current_order()
        if order:
            self.guard(
                lambda: self.ctx.orders.mark_ready(order.order_id, self.user_id),
                "已出餐，配送单已进入抢单池",
            )

    # ================================================================== #
    # 退款
    # ================================================================== #
    def _build_refund_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="退款处理")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="刷新", command=self.safe_refresh).pack(side="left")
        ttk.Button(
            toolbar, text="同意退款", style="Accent.TButton", command=lambda: self._handle_refund(True)
        ).pack(side="left", padx=6)
        ttk.Button(toolbar, text="驳回", command=lambda: self._handle_refund(False)).pack(
            side="left"
        )
        ttk.Label(
            toolbar, text="10 分钟未处理将自动同意", style="Muted.TLabel"
        ).pack(side="left", padx=12)

        self.refund_frame, self.refund_tree = make_table(
            tab,
            [
                ("id", "退款单", 100),
                ("order", "订单号", 110),
                ("amount", "金额", 80),
                ("reason", "原因", 220),
                ("deadline", "处理截止", 100),
            ],
            height=12,
        )
        self.refund_frame.pack(fill="both", expand=True)

    def _refresh_refunds(self) -> None:
        clear_tree(self.refund_tree)
        for refund in self.ctx.refunds.pending_for_store(self.user_id):
            add_row(
                self.refund_tree,
                refund.refund_id,
                (
                    refund.refund_id,
                    refund.order_id,
                    f"¥{refund.amount:.2f}",
                    refund.reason,
                    fmt_time(refund.deadline),
                ),
            )

    def _handle_refund(self, approve: bool) -> None:
        refund_id = selected_id(self.refund_tree)
        if not refund_id:
            messagebox.showinfo("提示", "请先选择退款单", parent=self)
            return
        comment = simpledialog.askstring(
            "处理退款", "处理意见（可留空）：", parent=self
        )
        if comment is None:
            return
        self.guard(
            lambda: self.ctx.refunds.merchant_handle(
                refund_id, self.user_id, approve=approve, comment=comment or ""
            ),
            "已同意退款" if approve else "已驳回退款",
        )

    # ================================================================== #
    # 消息
    # ================================================================== #
    def _build_message_tab(self) -> None:
        self.message_panel = MessagePanel(self.notebook, self.ctx, self.user_id, self.app)
        self.notebook.add(self.message_panel, text="消息")

    # ================================================================== #
    def refresh(self) -> None:
        self._refresh_store_tab()
        self._refresh_dishes()
        self._refresh_orders()
        self._refresh_refunds()
        self.message_panel.refresh()


class EditDishDialog(ModalDialog):
    def __init__(self, parent, ctx, merchant_id: str, dish_id: str) -> None:
        super().__init__(parent, "修改菜品")
        self.ctx = ctx
        self.merchant_id = merchant_id
        self.dish = ctx.repos.dishes.get(dish_id)
        self.name = tk.StringVar(value=self.dish.name)
        self.price = tk.StringVar(value=f"{self.dish.price:.2f}")
        self.stock = tk.StringVar(value=str(self.dish.stock))
        self.desc = tk.StringVar(value=self.dish.description)
        add_field(self.body, 0, 0, "名称", self.name)
        add_field(self.body, 1, 0, "价格", self.price, width=8)
        add_field(self.body, 1, 2, "库存", self.stock, width=8)
        add_field(self.body, 2, 0, "说明", self.desc, width=32)
        ttk.Button(
            self.body, text="保存", style="Accent.TButton", command=self._save
        ).grid(row=3, column=0, sticky="w", pady=(12, 0))

    def _save(self) -> None:
        try:
            self.ctx.stores.update_dish(
                self.merchant_id,
                self.dish.dish_id,
                name=self.name.get(),
                price=self.price.get(),
                stock=int(self.stock.get()),
                description=self.desc.get(),
            )
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        self.result = True
        self.destroy()
