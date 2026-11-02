"""顾客端：点餐、购物车、订单、地址与消息。"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk

from app.domain.enums import OrderStatus
from app.domain.pricing import distance_km
from app.ui.base import BaseView, ModalDialog
from app.ui.panels import MessagePanel
from app.ui.theme import RED
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


class CustomerView(BaseView):
    def __init__(self, master, app, user_id: str) -> None:
        super().__init__(master, app, user_id)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        self._address_display: dict[str, str] = {}
        self._build_menu_tab()
        self._build_cart_tab()
        self._build_orders_tab()
        self._build_address_tab()
        self._build_message_tab()
        self.notebook.bind("<<NotebookTabChanged>>", lambda _e: self.safe_refresh())

    # ================================================================== #
    # 点餐
    # ================================================================== #
    def _build_menu_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="点餐")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 8))
        self.search_var = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.search_var, width=26).pack(side="left")
        ttk.Button(toolbar, text="搜索", command=self._refresh_stores).pack(
            side="left", padx=6
        )
        self.only_open = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            toolbar, text="只看营业中", variable=self.only_open, command=self._refresh_stores
        ).pack(side="left", padx=6)
        ttk.Label(
            toolbar, text="可按店铺名或菜品名搜索", style="Muted.TLabel"
        ).pack(side="left", padx=8)

        paned = ttk.Panedwindow(tab, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned, padding=(0, 0, 8, 0))
        self.store_frame, self.store_tree = make_table(
            left,
            [
                ("name", "店铺", 150),
                ("rating", "评分", 50),
                ("min", "起送", 60),
                ("status", "状态", 60),
            ],
            height=16,
        )
        self.store_frame.pack(fill="both", expand=True)
        self.store_tree.bind("<<TreeviewSelect>>", lambda _e: self._load_menu())
        paned.add(left, weight=1)

        right = ttk.Frame(paned)
        self.store_title = ttk.Label(right, text="请选择左侧店铺", style="H2.TLabel")
        self.store_title.pack(anchor="w")
        self.store_notice = ttk.Label(right, text="", style="Muted.TLabel", wraplength=620)
        self.store_notice.pack(anchor="w", pady=(2, 8))

        self.menu_frame, self.menu_tree = make_table(
            right,
            [
                ("category", "分类", 80),
                ("name", "菜品", 150),
                ("price", "单价", 70),
                ("stock", "库存", 60),
                ("status", "状态", 70),
                ("desc", "说明", 220),
            ],
            height=13,
        )
        self.menu_frame.pack(fill="both", expand=True)

        cart_bar = ttk.Frame(right)
        cart_bar.pack(fill="x", pady=(8, 0))
        ttk.Label(cart_bar, text="数量", style="Muted.TLabel").pack(side="left")
        self.qty_var = tk.IntVar(value=1)
        ttk.Spinbox(
            cart_bar, from_=1, to=99, textvariable=self.qty_var, width=5
        ).pack(side="left", padx=(6, 12))
        ttk.Button(
            cart_bar, text="加入购物车", style="Accent.TButton", command=self._add_to_cart
        ).pack(side="left")
        self.menu_cart_label = ttk.Label(cart_bar, text="", style="Muted.TLabel")
        self.menu_cart_label.pack(side="left", padx=12)
        paned.add(right, weight=3)

    def _refresh_stores(self) -> None:
        selected = selected_id(self.store_tree)
        clear_tree(self.store_tree)
        stores = self.ctx.stores.search_stores(
            self.search_var.get() if hasattr(self, "search_var") else "",
            only_open=self.only_open.get() if hasattr(self, "only_open") else True,
        )
        for store in stores:
            add_row(
                self.store_tree,
                store.store_id,
                (
                    store.name,
                    f"{store.rating:.1f}",
                    f"¥{store.min_order_amount:.0f}",
                    store.status.label,
                ),
                tag=None if store.is_open else "muted",
            )
        if selected and self.store_tree.exists(selected):
            self.store_tree.selection_set(selected)
        elif stores:
            self.store_tree.selection_set(stores[0].store_id)
        self._load_menu()

    def _load_menu(self) -> None:
        store_id = selected_id(self.store_tree)
        clear_tree(self.menu_tree)
        if not store_id:
            return
        store = self.ctx.stores.store_detail(store_id)
        distance = self._distance_to_store(store)
        self.store_title.configure(
            text=f"{store.name}　{distance}　起送 ¥{store.min_order_amount:.2f}"
        )
        self.store_notice.configure(text=store.notice or store.description)
        for section in self.ctx.stores.menu(store_id):
            for dish in section.dishes:
                add_row(
                    self.menu_tree,
                    dish.dish_id,
                    (
                        section.category.name,
                        dish.name,
                        f"¥{dish.price:.2f}",
                        dish.stock,
                        dish.status.label,
                        dish.description or "-",
                    ),
                    tag=None if dish.is_available else "muted",
                )
        self._refresh_cart_labels()

    def _distance_to_store(self, store) -> str:
        address = self.ctx.users.default_address(self.user_id)
        if address is None:
            return "未设置地址"
        value = distance_km(store.x_km, store.y_km, address.x_km, address.y_km)
        return f"距默认地址 {value:.2f} km"

    def _add_to_cart(self) -> None:
        dish_id = selected_id(self.menu_tree)
        if not dish_id:
            messagebox.showinfo("提示", "请先选择菜品", parent=self)
            return
        result = self.guard(
            lambda: self.ctx.cart.add_item(self.user_id, dish_id, int(self.qty_var.get())),
            success="已加入购物车",
        )
        if result:
            self._refresh_cart_labels()

    def _refresh_cart_labels(self) -> None:
        summary = self.ctx.cart.summary(self.user_id)
        text = f"购物车 {summary.total_quantity} 件 · ¥{summary.goods_amount:.2f}"
        for label in (self.menu_cart_label, self.cart_summary_label):
            if label.winfo_exists():
                label.configure(text=text)

    # ================================================================== #
    # 购物车
    # ================================================================== #
    def _build_cart_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="购物车与结算")

        self.cart_summary_label = ttk.Label(tab, text="", style="H2.TLabel")
        self.cart_summary_label.pack(anchor="w")
        self.cart_issue_label = ttk.Label(tab, text="", style="Muted.TLabel", foreground=RED)
        self.cart_issue_label.pack(anchor="w", pady=(2, 8))

        self.cart_frame, self.cart_tree = make_table(
            tab,
            [
                ("name", "菜品", 200),
                ("price", "单价", 80),
                ("qty", "数量", 60),
                ("subtotal", "小计", 90),
                ("status", "库存状态", 100),
            ],
            height=9,
        )
        self.cart_frame.pack(fill="both", expand=True)

        controls = ttk.Frame(tab)
        controls.pack(fill="x", pady=(8, 0))
        ttk.Label(controls, text="数量", style="Muted.TLabel").pack(side="left")
        self.cart_qty = tk.IntVar(value=1)
        ttk.Spinbox(
            controls, from_=1, to=99, textvariable=self.cart_qty, width=5
        ).pack(side="left", padx=6)
        ttk.Button(controls, text="修改数量", command=self._update_cart_qty).pack(side="left")
        ttk.Button(controls, text="删除", command=self._remove_cart_item).pack(
            side="left", padx=6
        )
        ttk.Button(controls, text="清空", command=self._clear_cart).pack(side="left")

        checkout = ttk.LabelFrame(tab, text="结算信息", padding=12)
        checkout.pack(fill="x", pady=(12, 0))
        ttk.Label(checkout, text="收货地址", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.address_combo = ttk.Combobox(checkout, state="readonly", width=48)
        self.address_combo.grid(row=0, column=1, sticky="w", padx=8, pady=3)
        ttk.Label(checkout, text="备注", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w"
        )
        self.remark_var = tk.StringVar()
        ttk.Entry(checkout, textvariable=self.remark_var, width=50).grid(
            row=1, column=1, sticky="w", padx=8, pady=3
        )
        actions = ttk.Frame(checkout)
        actions.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(
            actions, text="提交订单（待支付）", style="Accent.TButton", command=self._checkout
        ).pack(side="left")
        ttk.Button(
            actions, text="提交并模拟支付", command=lambda: self._checkout(pay_now=True)
        ).pack(side="left", padx=8)

    def _refresh_cart(self) -> None:
        summary = self.ctx.cart.summary(self.user_id)
        selected = selected_id(self.cart_tree)
        clear_tree(self.cart_tree)
        for line in summary.lines:
            dish = line.dish
            stock_text = (
                f"库存 {dish.stock}" if dish else "菜品不存在"
            )
            if dish is not None and not line.available:
                stock_text = "库存不足"
            add_row(
                self.cart_tree,
                line.item.dish_id,
                (
                    line.item.dish_name,
                    f"¥{line.item.unit_price:.2f}",
                    line.item.quantity,
                    f"¥{line.item.subtotal:.2f}",
                    stock_text,
                ),
                tag=None if line.available else "refund",
            )
        if selected and self.cart_tree.exists(selected):
            self.cart_tree.selection_set(selected)
        self._refresh_cart_labels()
        self.cart_issue_label.configure(text="；".join(summary.issues))
        self._refresh_address_combo()
        if summary.store is not None:
            self.cart_summary_label.configure(
                text=(
                    f"{summary.store.name} · {summary.total_quantity} 件 · "
                    f"商品 ¥{summary.goods_amount:.2f}"
                )
            )
        else:
            self.cart_summary_label.configure(text="购物车为空")

    def _refresh_address_combo(self) -> None:
        addresses = self.ctx.users.list_addresses(self.user_id)
        current = self.address_combo.get()
        self._address_display = {
            f"{a.detail}（{a.receiver}）": a.address_id for a in addresses
        }
        values = list(self._address_display)
        self.address_combo.configure(values=values)
        default = self.ctx.users.default_address(self.user_id)
        if current in self._address_display:
            self.address_combo.set(current)
        elif default is not None:
            for text, address_id in self._address_display.items():
                if address_id == default.address_id:
                    self.address_combo.set(text)
                    break
        elif values:
            self.address_combo.set(values[0])
        else:
            self.address_combo.set("")

    def _update_cart_qty(self) -> None:
        dish_id = selected_id(self.cart_tree)
        if not dish_id:
            return
        self.guard(
            lambda: self.ctx.cart.update_quantity(
                self.user_id, dish_id, int(self.cart_qty.get())
            ),
            success="数量已更新",
        )

    def _remove_cart_item(self) -> None:
        dish_id = selected_id(self.cart_tree)
        if dish_id:
            self.guard(lambda: self.ctx.cart.remove_item(self.user_id, dish_id), "已移除")

    def _clear_cart(self) -> None:
        if messagebox.askyesno("清空购物车", "确定清空购物车吗？", parent=self):
            self.guard(lambda: self.ctx.cart.clear(self.user_id), "购物车已清空")

    def _checkout(self, pay_now: bool = False) -> None:
        display = self.address_combo.get()
        address_id = self._address_display.get(display)
        if not address_id:
            messagebox.showinfo("提示", "请先添加并选择收货地址", parent=self)
            self.notebook.select(3)
            return
        key = f"UI-{self.user_id}-{datetime.now().timestamp():.0f}"
        result = self.guard(
            lambda: self.ctx.orders.checkout(
                self.user_id,
                address_id,
                remark=self.remark_var.get(),
                idempotency_key=key,
            )
        )
        if result is None:
            return
        order = result.order
        self.app.set_status(f"已生成订单 {order.order_id}，应付 ¥{order.payable_amount:.2f}")
        self.notebook.select(2)
        if pay_now:
            self._simulate_pay(order.order_id)
        self.safe_refresh()

    # ================================================================== #
    # 我的订单
    # ================================================================== #
    def _build_orders_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="我的订单")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="刷新", command=self._refresh_orders).pack(side="left")
        for text, command in (
            ("支付", self._pay_order),
            ("取消订单", self._cancel_order),
            ("确认收货", self._confirm_receipt),
            ("申请退款", self._apply_refund),
            ("评价", self._review),
        ):
            ttk.Button(toolbar, text=text, command=command).pack(side="left", padx=4)

        self.order_frame, self.order_tree = make_table(
            tab,
            [
                ("id", "订单号", 110),
                ("store", "店铺", 120),
                ("amount", "金额", 80),
                ("status", "状态", 80),
                ("created", "下单时间", 100),
            ],
            height=8,
        )
        self.order_frame.pack(fill="both", expand=True)
        self.order_tree.bind("<<TreeviewSelect>>", lambda _e: self._show_order_detail())

        ttk.Label(tab, text="订单详情", style="Muted.TLabel").pack(anchor="w", pady=(8, 2))
        self.order_detail = make_detail(tab, height=11)
        self.order_detail.pack(fill="both", expand=True)

    def _refresh_orders(self) -> None:
        selected = selected_id(self.order_tree)
        clear_tree(self.order_tree)
        for order in self.ctx.orders.list_for_customer(self.user_id):
            add_row(
                self.order_tree,
                order.order_id,
                (
                    order.order_id,
                    order.store_name,
                    f"¥{order.payable_amount:.2f}",
                    order.status.label,
                    fmt_time(order.created_at),
                ),
                tag=status_tag(order.status.label),
            )
        if selected and self.order_tree.exists(selected):
            self.order_tree.selection_set(selected)
        elif self.order_tree.get_children():
            first = self.order_tree.get_children()[0]
            self.order_tree.selection_set(first)
        self._show_order_detail()

    def _current_order(self):
        order_id = selected_id(self.order_tree)
        if not order_id:
            messagebox.showinfo("提示", "请先选择订单", parent=self)
            return None
        return self.ctx.repos.orders.get(order_id)

    def _show_order_detail(self) -> None:
        order_id = selected_id(self.order_tree)
        if not order_id:
            set_detail(self.order_detail, "")
            return
        order = self.ctx.repos.orders.get(order_id)
        lines = [
            f"订单号：{order.order_id}　　状态：{order.status.label}",
            f"店铺：{order.store_name}　　下单：{order.created_at:%Y-%m-%d %H:%M:%S}",
            f"收货：{order.address.detail}（{order.address.receiver} {order.address.phone}）",
            f"备注：{order.remark or '无'}",
            "",
            "商品明细：",
        ]
        for item in order.items:
            lines.append(
                f"  {item.dish_name}　¥{item.unit_price:.2f} × "
                f"{item.quantity} = ¥{item.subtotal:.2f}"
            )
        lines += [
            "",
            f"商品 ¥{order.goods_amount:.2f}　打包 ¥{order.packing_fee:.2f}　"
            f"配送 ¥{order.delivery_fee:.2f}　优惠 -¥{order.discount_amount:.2f}　"
            f"实付 ¥{order.payable_amount:.2f}",
        ]
        if order.fee_note:
            lines.append(f"说明：{order.fee_note}")
        if order.status is OrderStatus.PENDING_PAYMENT and order.pay_deadline:
            lines.append(f"支付截止：{order.pay_deadline:%H:%M:%S}（15 分钟内有效）")
        if order.status is OrderStatus.PENDING_ACCEPTANCE and order.accept_deadline:
            lines.append(f"商家接单截止：{order.accept_deadline:%H:%M:%S}")
        if order.cancel_reason:
            lines.append(f"取消原因：{order.cancel_reason}")

        refund = self.ctx.refunds.for_order(order.order_id)
        if refund is not None:
            lines += [
                "",
                f"退款单 {refund.refund_id}：{refund.status.label}　"
                f"金额 ¥{refund.amount:.2f}　原因：{refund.reason}",
            ]
            if refund.comment:
                lines.append(f"处理意见：{refund.comment}")
        payment = self.ctx.payments.payment_of(order.order_id)
        if payment is not None:
            lines.append(
                f"支付：{payment.status.label}　流水 {payment.transaction_no or '-'}"
            )
        lines += ["", "状态轨迹："]
        for change in order.status_history:
            lines.append(
                f"  {change.changed_at:%m-%d %H:%M:%S}　{change.status.label}"
                f"　{change.note or ''}"
            )
        review = self.ctx.repos.reviews.by_order(order.order_id)
        if review is not None:
            lines += ["", f"我的评价：{review.rating} 星　{review.content}"]
        set_detail(self.order_detail, "\n".join(lines))

    # ------------------------------------------------------------------ #
    def _simulate_pay(self, order_id: str) -> None:
        answer = messagebox.askyesnocancel(
            "模拟支付",
            "是否模拟支付成功？\n\n是 = 支付成功\n否 = 模拟支付失败（订单取消并回滚库存）\n取消 = 暂不支付",
            parent=self,
        )
        if answer is None:
            return
        self.guard(
            lambda: self.ctx.orders.pay(order_id, self.user_id, success=answer),
            "支付成功" if answer else "模拟支付失败，订单已取消",
        )

    def _pay_order(self) -> None:
        order = self._current_order()
        if order is None:
            return
        if order.status is not OrderStatus.PENDING_PAYMENT:
            messagebox.showinfo("提示", f"订单当前为「{order.status.label}」", parent=self)
            return
        self._simulate_pay(order.order_id)

    def _cancel_order(self) -> None:
        order = self._current_order()
        if order is None:
            return
        if not messagebox.askyesno("取消订单", f"确定取消订单 {order.order_id} 吗？", parent=self):
            return
        self.guard(
            lambda: self.ctx.orders.cancel(order.order_id, self.user_id, "顾客主动取消"),
            "订单已取消",
        )

    def _confirm_receipt(self) -> None:
        order = self._current_order()
        if order is None:
            return
        self.guard(
            lambda: self.ctx.orders.confirm_receipt(order.order_id, self.user_id),
            "已确认收货",
        )

    def _apply_refund(self) -> None:
        order = self._current_order()
        if order is None:
            return
        reason = simpledialog.askstring(
            "申请退款", "请填写退款原因：", parent=self
        )
        if not reason:
            return
        refund = self.guard(
            lambda: self.ctx.refunds.apply(order.order_id, self.user_id, reason),
            "退款申请已提交，等待商家处理",
        )
        if refund:
            self.safe_refresh()

    def _review(self) -> None:
        order = self._current_order()
        if order is None:
            return
        dialog = ReviewDialog(self, order.order_id)
        result = dialog.show()
        if result is None:
            return
        rating, content = result
        self.guard(
            lambda: self.ctx.orders.review(order.order_id, self.user_id, rating, content),
            "评价已提交",
        )

    # ================================================================== #
    # 地址
    # ================================================================== #
    def _build_address_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="收货地址")

        self.address_frame, self.address_tree = make_table(
            tab,
            [
                ("receiver", "收货人", 90),
                ("phone", "电话", 120),
                ("detail", "地址", 300),
                ("coord", "模拟坐标", 100),
                ("default", "默认", 60),
            ],
            height=10,
        )
        self.address_frame.pack(fill="both", expand=True)

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(8, 0))
        ttk.Button(toolbar, text="设为默认", command=self._set_default_address).pack(side="left")
        ttk.Button(toolbar, text="删除", style="Danger.TButton", command=self._delete_address).pack(
            side="left", padx=6
        )

        form = ttk.LabelFrame(tab, text="新增地址（坐标单位为公里，用于模拟配送距离）", padding=12)
        form.pack(fill="x", pady=(12, 0))
        self.addr_receiver = tk.StringVar()
        self.addr_phone = tk.StringVar(value="")
        self.addr_detail = tk.StringVar()
        self.addr_x = tk.StringVar(value="1.0")
        self.addr_y = tk.StringVar(value="1.0")
        add_field(form, 0, 0, "收货人", self.addr_receiver)
        add_field(form, 0, 2, "电话", self.addr_phone)
        add_field(form, 1, 0, "详细地址", self.addr_detail, width=34)
        add_field(form, 2, 0, "坐标 x", self.addr_x, width=8)
        add_field(form, 2, 2, "坐标 y", self.addr_y, width=8)
        self.addr_default = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="设为默认地址", variable=self.addr_default).grid(
            row=2, column=4, sticky="w"
        )
        ttk.Button(
            form, text="保存地址", style="Accent.TButton", command=self._add_address
        ).grid(row=3, column=0, sticky="w", pady=(10, 0))

    def _refresh_addresses(self) -> None:
        clear_tree(self.address_tree)
        for address in self.ctx.users.list_addresses(self.user_id):
            add_row(
                self.address_tree,
                address.address_id,
                (
                    address.receiver,
                    address.phone,
                    address.detail,
                    f"({address.x_km}, {address.y_km})",
                    "是" if address.is_default else "",
                ),
            )
        self._refresh_address_combo()

    def _add_address(self) -> None:
        self.guard(
            lambda: self.ctx.users.add_address(
                self.user_id,
                receiver=self.addr_receiver.get(),
                phone=self.addr_phone.get(),
                detail=self.addr_detail.get(),
                x_km=float(self.addr_x.get() or 0),
                y_km=float(self.addr_y.get() or 0),
                set_default=self.addr_default.get(),
            ),
            "地址已保存",
        )

    def _set_default_address(self) -> None:
        address_id = selected_id(self.address_tree)
        if address_id:
            self.guard(
                lambda: self.ctx.users.set_default_address(self.user_id, address_id),
                "默认地址已更新",
            )

    def _delete_address(self) -> None:
        address_id = selected_id(self.address_tree)
        if address_id and messagebox.askyesno("删除地址", "确定删除该地址吗？", parent=self):
            self.guard(
                lambda: self.ctx.users.delete_address(self.user_id, address_id), "地址已删除"
            )

    # ================================================================== #
    # 消息
    # ================================================================== #
    def _build_message_tab(self) -> None:
        self.message_panel = MessagePanel(self.notebook, self.ctx, self.user_id, self.app)
        self.notebook.add(self.message_panel, text="消息")

    # ================================================================== #
    def refresh(self) -> None:
        self._refresh_stores()
        self._refresh_cart()
        self._refresh_orders()
        self._refresh_addresses()
        self.message_panel.refresh()


class ReviewDialog(ModalDialog):
    def __init__(self, parent, order_id: str) -> None:
        super().__init__(parent, f"评价订单 {order_id}")
        ttk.Label(self.body, text="评分", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.rating = tk.StringVar(value="5")
        ttk.Combobox(
            self.body,
            textvariable=self.rating,
            values=["5", "4", "3", "2", "1"],
            state="readonly",
            width=6,
        ).grid(row=0, column=1, sticky="w", pady=4)
        ttk.Label(self.body, text="评价内容", style="Muted.TLabel").grid(
            row=1, column=0, sticky="nw", pady=(8, 0)
        )
        self.text = tk.Text(self.body, width=40, height=6, wrap="word")
        self.text.grid(row=1, column=1, pady=(8, 0))
        ttk.Button(
            self.body, text="提交评价", style="Accent.TButton", command=self._submit
        ).grid(row=2, column=1, sticky="e", pady=(12, 0))

    def _submit(self) -> None:
        self.result = (int(self.rating.get()), self.text.get("1.0", "end").strip())
        self.destroy()
