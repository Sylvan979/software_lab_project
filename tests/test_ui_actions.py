"""界面按钮测试：逐个点击四端按钮并校验业务结果。

测试不依赖人工操作：构造真实的 Tk 窗口，用 ``invoke()`` 触发按钮，
替换消息框与模态对话框，最后同时断言"没有未捕获异常""没有系统错误弹窗"
以及服务层数据确实发生了变化。
"""

from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from unittest.mock import patch
from uuid import uuid4

from app.config import Settings
from app.container import build_context
from app.domain.enums import (
    AccountStatus,
    DeliveryStatus,
    DishStatus,
    OrderStatus,
    PaymentStatus,
    RefundStatus,
    ResponsibleParty,
    StoreStatus,
    UserRole,
)
from app.seed import DEMO_CODE, seed_demo_data
from app.ui.admin import AdminView, ArbitrationDialog
from app.ui.app import MainApp
from app.ui.customer import CustomerView, ReviewDialog
from app.ui.dialogs import ChoiceDialog, TextDialog
from app.ui.login import DEMO_DATA, LoginView
from app.ui.merchant import EditDishDialog, MerchantView
from app.ui.rider import RiderView


def walk(widget: tk.Misc):
    """深度遍历控件树。"""
    for child in widget.winfo_children():
        yield child
        yield from walk(child)


class UiTestCase(unittest.TestCase):
    """公共夹具：临时数据库 + 独立 Tk 主窗口 + 消息框替身。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        settings = Settings(data_dir=Path(self._tmp.name))
        self.ctx = build_context(settings)
        self.ids = seed_demo_data(self.ctx)

        self.calls: list[tuple[str, str, str]] = []
        self.yesno = True
        self.pay_answer: bool | None = True
        self.askstring_value: str | None = "餐品撒漏"
        self.dialog_results = {
            ChoiceDialog: "缺货",
            TextDialog: "测试原因",
            ArbitrationDialog: (True, ResponsibleParty.MERCHANT, "平台判定商家责任"),
            ReviewDialog: (5, "味道很好"),
            EditDishDialog: None,
        }

        self._patches = [
            patch("app.ui.app.build_context", return_value=self.ctx),
            patch.object(messagebox, "showinfo", side_effect=self._record_info),
            patch.object(messagebox, "showerror", side_effect=self._record_error),
            patch.object(messagebox, "showwarning", side_effect=self._record_warning),
            patch.object(messagebox, "askyesno", side_effect=lambda *a, **k: self.yesno),
            patch.object(
                messagebox, "askyesnocancel", side_effect=lambda *a, **k: self.pay_answer
            ),
            patch.object(
                simpledialog, "askstring", side_effect=lambda *a, **k: self.askstring_value
            ),
        ]
        for cls in (
            ChoiceDialog,
            TextDialog,
            ArbitrationDialog,
            ReviewDialog,
            EditDishDialog,
        ):
            self._patches.append(
                patch.object(
                    cls,
                    "show",
                    new=lambda dialog, _cls=cls: self.dialog_results.get(_cls),
                )
            )
        for patcher in self._patches:
            patcher.start()

        self.callback_errors: list[BaseException] = []
        self.app = MainApp()
        self.app.withdraw()
        self.app.report_callback_exception = self._callback_error
        self.app.update()

    def tearDown(self) -> None:
        try:
            self.app.destroy()
        finally:
            patch.stopall()
            self._tmp.cleanup()

    # ------------------------------------------------------------------ #
    # 消息框替身
    # ------------------------------------------------------------------ #
    def _record_info(self, title: str, message: str = "", **_kwargs) -> None:
        self.calls.append(("info", title, message))

    def _record_error(self, title: str, message: str = "", **_kwargs) -> None:
        self.calls.append(("error", title, message))

    def _record_warning(self, title: str, message: str = "", **_kwargs) -> None:
        self.calls.append(("warning", title, message))

    def _callback_error(self, exc, value, _tb) -> None:
        self.callback_errors.append(value)

    # ------------------------------------------------------------------ #
    # 断言与操作辅助
    # ------------------------------------------------------------------ #
    def assert_clean(self) -> None:
        """没有未捕获异常，也没有"系统错误"弹窗。"""
        if self.callback_errors:
            self.fail(f"界面回调抛出未捕获异常：{self.callback_errors!r}")
        system_errors = [c for c in self.calls if c[0] == "error" and c[1] == "系统错误"]
        if system_errors:
            self.fail(f"出现系统错误弹窗：{system_errors!r}")

    def messages(self, kind: str) -> list[tuple[str, str, str]]:
        return [call for call in self.calls if call[0] == kind]

    def find_widget(self, container: tk.Misc, text: str):
        for widget in walk(container):
            if isinstance(widget, (ttk.Button, ttk.Checkbutton)):
                if widget.cget("text") == text:
                    return widget
        self.fail(f"未找到文字为「{text}」的按钮")
        return None

    def click(self, container: tk.Misc, text: str):
        widget = self.find_widget(container, text)
        self.assertNotIn("disabled", widget.state(), f"按钮「{text}」不可点击")
        widget.invoke()
        self.app.update()
        self.assert_clean()
        return widget

    def login_as(self, phone: str):
        session = self.ctx.auth.login(phone, DEMO_CODE)
        self.app.on_login(session)
        self.app.update()
        return self.app.current_view

    def select(self, tree: ttk.Treeview, iid: str) -> None:
        tree.selection_set(iid)
        self.app.update()

    def clear_selection(self, tree: ttk.Treeview) -> None:
        tree.selection_remove(*tree.selection())
        self.app.update()

    # ------------------------------------------------------------------ #
    # 业务数据辅助
    # ------------------------------------------------------------------ #
    def place(self, dish_key: str = "dish_a_hot", qty: int = 1, customer: str | None = None):
        customer = customer or self.ids["customer"]
        address = self.ctx.users.default_address(customer)
        assert address is not None
        self.ctx.cart.add_item(customer, self.ids[dish_key], qty)
        return self.ctx.orders.checkout(
            customer, address.address_id, idempotency_key=uuid4().hex
        ).order

    def ready_order(self):
        order = self.place()
        customer = self.ids["customer"]
        self.ctx.orders.pay(order.order_id, customer)
        self.ctx.orders.merchant_accept(order.order_id, self.ids["merchant_a"])
        self.ctx.orders.mark_ready(order.order_id, self.ids["merchant_a"])
        task = self.ctx.repos.deliveries.by_order(order.order_id)
        assert task is not None
        return self.ctx.repos.orders.get(order.order_id), task

    def delivered_order(self):
        order, task = self.ready_order()
        self.ctx.delivery.grab(task.task_id, self.ids["rider"])
        self.ctx.delivery.pickup(task.task_id, self.ids["rider"])
        self.ctx.delivery.deliver(task.task_id, self.ids["rider"])
        return self.ctx.repos.orders.get(order.order_id)

    def delivering_order(self):
        order, task = self.ready_order()
        self.ctx.delivery.grab(task.task_id, self.ids["rider"])
        self.ctx.delivery.pickup(task.task_id, self.ids["rider"])
        return self.ctx.repos.orders.get(order.order_id), task

    def failed_order(self):
        order, task = self.delivering_order()
        self.ctx.delivery.report_exception(
            task.task_id, self.ids["rider"], "联系不上顾客"
        )
        return self.ctx.repos.orders.get(order.order_id), task

    def new_merchant_with_pending_store(self, phone: str = "13911112222") -> str:
        merchant = self.ctx.auth.register(phone, "新商家", UserRole.MERCHANT, DEMO_CODE)
        self.ctx.stores.apply_store(
            merchant.user_id,
            name="新店",
            description="简餐",
            address_text="学府路 30 号",
            x_km=0.4,
            y_km=0.4,
            min_order_amount="10.00",
        )
        return merchant.user_id


# ====================================================================== #
# 登录与注册
# ====================================================================== #
class LoginViewTest(UiTestCase):
    def setUp(self) -> None:
        super().setUp()
        assert isinstance(self.app.current_view, LoginView)
        self.view: LoginView = self.app.current_view

    def test_demo_buttons_fill_each_account(self) -> None:
        for label, phone in DEMO_DATA:
            self.click(self.view, label)
            self.assertEqual(self.view.login_phone.get(), phone)
            self.assertEqual(self.view.login_code.get(), DEMO_CODE)

    def test_login_button_enters_customer_workspace(self) -> None:
        self.click(self.view, "登录")
        self.assertIsInstance(self.app.current_view, CustomerView)
        self.assertIsNotNone(self.app.session)
        self.assertEqual(self.app.user.nickname, "陈晓")

    def test_login_with_wrong_code_reports_business_error(self) -> None:
        self.view.login_code.set("000000")
        self.click(self.view, "登录")
        self.assertIsInstance(self.app.current_view, LoginView)
        self.assertTrue(
            any(kind == "error" and title == "登录失败" for kind, title, _ in self.calls)
        )

    def test_request_code_button_shows_demo_code(self) -> None:
        self.click(self.view, "获取验证码")
        infos = self.messages("info")
        self.assertTrue(infos)
        self.assertIn(DEMO_CODE, infos[-1][2])

    def test_register_button_rejects_invalid_phone(self) -> None:
        self.view.reg_phone.set("123")
        self.view.reg_nickname.set("新用户")
        self.click(self.view, "注册并登录")
        self.assertIsInstance(self.app.current_view, LoginView)
        self.assertTrue(
            any(title == "注册失败" for kind, title, _ in self.calls if kind == "error")
        )

    def test_register_button_creates_customer_and_logs_in(self) -> None:
        self.view.reg_phone.set("13511112222")
        self.view.reg_nickname.set("新用户")
        self.click(self.view, "注册并登录")
        self.assertIsInstance(self.app.current_view, CustomerView)
        user = self.ctx.repos.users.get(self.app.user.user_id)
        self.assertEqual(user.nickname, "新用户")
        self.assertIs(user.role, UserRole.CUSTOMER)

    def test_logout_cancel_keeps_current_session(self) -> None:
        self.click(self.view, "登录")
        self.yesno = False
        self.click(self.app.header, "退出登录")
        self.assertIsInstance(self.app.current_view, CustomerView)
        self.assertIsNotNone(self.app.session)

    def test_logout_confirm_returns_to_login(self) -> None:
        self.click(self.view, "登录")
        self.yesno = True
        self.click(self.app.header, "退出登录")
        self.assertIsInstance(self.app.current_view, LoginView)
        self.assertIsNone(self.app.session)


# ====================================================================== #
# 顾客端
# ====================================================================== #
class CustomerViewTest(UiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.view = self.login_as("13800000001")
        assert isinstance(self.view, CustomerView)
        self.customer = self.ids["customer"]

    def test_search_and_checkbox_filter_stores(self) -> None:
        self.view.search_var.set("川味")
        self.click(self.view, "搜索")
        self.assertEqual(self.view.store_tree.get_children(), (self.ids["store_a"],))

        self.view.search_var.set("不存在的店铺")
        self.click(self.view, "搜索")
        self.assertEqual(self.view.store_tree.get_children(), ())

        self.view.search_var.set("")
        self.find_widget(self.view, "只看营业中").invoke()
        self.app.update()
        self.assert_clean()
        self.assertFalse(self.view.only_open.get())
        self.assertEqual(len(self.view.store_tree.get_children()), 2)

    def test_add_to_cart_requires_selection(self) -> None:
        self.clear_selection(self.view.menu_tree)
        self.click(self.view, "加入购物车")
        self.assertTrue(self.messages("info"))
        self.assertEqual(self.ctx.cart.summary(self.customer).total_quantity, 0)

    def test_add_to_cart_updates_summary(self) -> None:
        self.select(self.view.menu_tree, self.ids["dish_a_hot"])
        self.view.qty_var.set("2")
        self.click(self.view, "加入购物车")
        self.assertEqual(self.ctx.cart.summary(self.customer).total_quantity, 2)
        self.assertIn("2 件", self.view.menu_cart_label.cget("text"))

    def test_add_to_cart_rejects_invalid_quantity(self) -> None:
        self.select(self.view.menu_tree, self.ids["dish_a_hot"])
        self.view.qty_var.set("abc")
        self.click(self.view, "加入购物车")
        self.assertEqual(self.ctx.cart.summary(self.customer).total_quantity, 0)
        self.assertTrue(any("数量" in message for _k, _t, message in self.messages("info")))

    def test_cart_update_and_remove_buttons(self) -> None:
        cart_tab = self.view.cart_frame.master
        self.select(self.view.menu_tree, self.ids["dish_a_hot"])
        self.click(self.view, "加入购物车")
        self.select(self.view.cart_tree, self.ids["dish_a_hot"])
        self.view.cart_qty.set("3")
        self.click(cart_tab, "修改数量")
        self.assertEqual(self.ctx.cart.summary(self.customer).total_quantity, 3)
        self.click(cart_tab, "删除")
        self.assertEqual(self.ctx.cart.summary(self.customer).total_quantity, 0)

    def test_cart_buttons_without_selection_prompt(self) -> None:
        cart_tab = self.view.cart_frame.master
        self.clear_selection(self.view.cart_tree)
        self.click(cart_tab, "修改数量")
        self.click(cart_tab, "删除")
        self.assertGreaterEqual(len(self.messages("info")), 2)

    def test_cart_invalid_quantity_is_rejected(self) -> None:
        cart_tab = self.view.cart_frame.master
        self.select(self.view.menu_tree, self.ids["dish_a_hot"])
        self.click(self.view, "加入购物车")
        self.select(self.view.cart_tree, self.ids["dish_a_hot"])
        self.view.cart_qty.set("0")
        self.click(cart_tab, "修改数量")
        self.assertEqual(self.ctx.cart.summary(self.customer).total_quantity, 1)

    def test_clear_cart_respects_confirmation(self) -> None:
        self.select(self.view.menu_tree, self.ids["dish_a_hot"])
        self.click(self.view, "加入购物车")
        self.yesno = False
        self.click(self.view, "清空")
        self.assertEqual(self.ctx.cart.summary(self.customer).total_quantity, 1)
        self.yesno = True
        self.click(self.view, "清空")
        self.assertEqual(self.ctx.cart.summary(self.customer).total_quantity, 0)

    def test_checkout_without_address_prompts(self) -> None:
        for address in self.ctx.users.list_addresses(self.customer):
            self.ctx.users.delete_address(self.customer, address.address_id)
        self.view.safe_refresh()
        self.select(self.view.menu_tree, self.ids["dish_a_hot"])
        self.click(self.view, "加入购物车")
        self.click(self.view, "提交订单（待支付）")
        self.assertEqual(self.ctx.repos.orders.count(), 0)
        self.assertTrue(any("收货地址" in message for _k, _t, message in self.messages("info")))

    def test_checkout_empty_cart_reports_business_error(self) -> None:
        self.click(self.view, "提交订单（待支付）")
        self.assertEqual(self.ctx.repos.orders.count(), 0)
        self.assertTrue(
            any(title == "操作失败" for kind, title, _ in self.calls if kind == "error")
        )

    def test_checkout_pay_now_creates_paid_order(self) -> None:
        self.select(self.view.menu_tree, self.ids["dish_a_hot"])
        self.view.qty_var.set("2")
        self.click(self.view, "加入购物车")
        self.pay_answer = True
        self.click(self.view, "提交并模拟支付")
        self.assertEqual(self.ctx.repos.orders.count(), 1)
        order = self.ctx.repos.orders.all()[0]
        self.assertIs(order.status, OrderStatus.PENDING_ACCEPTANCE)
        payment = self.ctx.payments.payment_of(order.order_id)
        assert payment is not None
        self.assertIs(payment.status, PaymentStatus.PAID)

    def test_pay_button_failure_cancels_and_restores_stock(self) -> None:
        stock_before = self.ctx.repos.dishes.get(self.ids["dish_a_hot"]).stock
        self.select(self.view.menu_tree, self.ids["dish_a_hot"])
        self.click(self.view, "加入购物车")
        self.click(self.view, "提交订单（待支付）")
        order = self.ctx.repos.orders.all()[0]
        self.assertIs(order.status, OrderStatus.PENDING_PAYMENT)
        self.select(self.view.order_tree, order.order_id)
        self.pay_answer = False
        self.click(self.view, "支付")
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.CANCELLED)
        self.assertEqual(self.ctx.repos.dishes.get(self.ids["dish_a_hot"]).stock, stock_before)

    def test_pay_button_on_non_payable_order_shows_hint(self) -> None:
        order = self.ready_order()[0]
        self.view.safe_refresh()
        self.select(self.view.order_tree, order.order_id)
        self.click(self.view, "支付")
        self.assertTrue(
            any("订单当前为" in message for _k, _t, message in self.messages("info"))
        )

    def test_cancel_order_respects_confirmation(self) -> None:
        self.select(self.view.menu_tree, self.ids["dish_a_hot"])
        self.click(self.view, "加入购物车")
        self.click(self.view, "提交订单（待支付）")
        order = self.ctx.repos.orders.all()[0]
        self.select(self.view.order_tree, order.order_id)
        self.yesno = False
        self.click(self.view, "取消订单")
        self.assertIs(
            self.ctx.repos.orders.get(order.order_id).status, OrderStatus.PENDING_PAYMENT
        )
        self.yesno = True
        self.click(self.view, "取消订单")
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.CANCELLED)

    def test_checkout_twice_creates_two_orders(self) -> None:
        """同一秒内两次结算不能被误判为重复提交。"""
        self.select(self.view.menu_tree, self.ids["dish_a_hot"])
        self.click(self.view, "加入购物车")
        self.click(self.view, "提交订单（待支付）")
        self.select(self.view.menu_tree, self.ids["dish_a_hot"])
        self.click(self.view, "加入购物车")
        self.click(self.view, "提交订单（待支付）")
        self.assertEqual(self.ctx.repos.orders.count(), 2)

    def test_confirm_receipt_completes_order(self) -> None:
        order = self.delivered_order()
        self.view.safe_refresh()
        self.select(self.view.order_tree, order.order_id)
        self.click(self.view, "确认收货")
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.COMPLETED)

    def test_apply_refund_handles_cancel_and_submit(self) -> None:
        order, _task = self.delivering_order()
        self.view.safe_refresh()
        self.select(self.view.order_tree, order.order_id)
        self.askstring_value = None
        self.click(self.view, "申请退款")
        self.assertEqual(self.ctx.repos.refunds.count(), 0)
        self.askstring_value = "餐品撒漏"
        self.click(self.view, "申请退款")
        self.assertEqual(self.ctx.repos.refunds.count(), 1)
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.REFUNDING)

    def test_review_button_submits_rating(self) -> None:
        order = self.delivered_order()
        self.ctx.orders.confirm_receipt(order.order_id, self.customer)
        self.view.safe_refresh()
        self.select(self.view.order_tree, order.order_id)
        self.click(self.view, "评价")
        review = self.ctx.repos.reviews.by_order(order.order_id)
        assert review is not None
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.content, "味道很好")

    def test_address_buttons_add_default_and_delete(self) -> None:
        address_tab = self.view.address_frame.master
        before = len(self.ctx.users.list_addresses(self.customer))
        self.view.addr_receiver.set("陈晓")
        self.view.addr_phone.set("13800000001")
        self.view.addr_detail.set("幸福小区 9 栋 101")
        self.view.addr_x.set("1.2")
        self.view.addr_y.set("0.8")
        self.view.addr_default.set(False)
        self.click(self.view, "保存地址")
        self.assertEqual(len(self.ctx.users.list_addresses(self.customer)), before + 1)
        address = self.ctx.users.list_addresses(self.customer)[-1]

        self.select(self.view.address_tree, address.address_id)
        self.click(address_tab, "设为默认")
        self.assertTrue(self.ctx.repos.addresses.get(address.address_id).is_default)

        self.yesno = False
        self.click(address_tab, "删除")
        self.assertIsNotNone(self.ctx.repos.addresses.find(address.address_id))
        self.yesno = True
        self.click(address_tab, "删除")
        self.assertIsNone(self.ctx.repos.addresses.find(address.address_id))

    def test_address_buttons_reject_bad_coordinates(self) -> None:
        address_tab = self.view.address_frame.master
        before = len(self.ctx.users.list_addresses(self.customer))
        self.view.addr_receiver.set("陈晓")
        self.view.addr_phone.set("13800000001")
        self.view.addr_detail.set("幸福小区 9 栋 101")
        self.view.addr_x.set("西经三度")
        self.click(address_tab, "保存地址")
        self.assertEqual(len(self.ctx.users.list_addresses(self.customer)), before)
        self.assertTrue(any("坐标" in message for _k, _t, message in self.messages("info")))

    def test_address_actions_without_selection_prompt(self) -> None:
        address_tab = self.view.address_frame.master
        self.clear_selection(self.view.address_tree)
        self.click(address_tab, "设为默认")
        self.click(address_tab, "删除")
        self.assertGreaterEqual(len(self.messages("info")), 2)

    def test_message_mark_all_read(self) -> None:
        self.ctx.notifications.send(self.customer, "测试消息", "内容")
        self.view.safe_refresh()
        self.assertGreater(self.ctx.notifications.unread_count(self.customer), 0)
        self.click(self.view.message_panel, "全部标为已读")
        self.assertEqual(self.ctx.notifications.unread_count(self.customer), 0)
        self.click(self.view.message_panel, "刷新")


# ====================================================================== #
# 商家端
# ====================================================================== #
class MerchantViewTest(UiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.view = self.login_as("13900000001")
        assert isinstance(self.view, MerchantView)
        self.merchant = self.ids["merchant_a"]

    def test_toggle_business_button(self) -> None:
        self.click(self.view, "休息一下")
        self.assertFalse(self.ctx.repos.stores.get(self.ids["store_a"]).is_open)
        self.click(self.view, "开始营业")
        self.assertTrue(self.ctx.repos.stores.get(self.ids["store_a"]).is_open)

    def test_refresh_button(self) -> None:
        self.click(self.view, "刷新")
        self.assertTrue(self.view.dish_tree.get_children())

    def test_save_store_settings(self) -> None:
        self.view.notice_var.set("午市提前下单")
        self.view.min_order_var.set("18.50")
        self.view.accept_timeout_var.set("12")
        self.click(self.view, "保存设置")
        store = self.ctx.repos.stores.get(self.ids["store_a"])
        self.assertEqual(store.notice, "午市提前下单")
        self.assertEqual(str(store.min_order_amount), "18.50")
        self.assertEqual(store.accept_timeout_minutes, 12)

    def test_save_store_rejects_non_numeric_timeout(self) -> None:
        self.view.accept_timeout_var.set("十分钟")
        self.click(self.view, "保存设置")
        store = self.ctx.repos.stores.get(self.ids["store_a"])
        self.assertEqual(store.accept_timeout_minutes, 10)
        self.assertTrue(
            any("整数" in message for _k, _t, message in self.messages("info"))
        )

    def test_add_category_buttons(self) -> None:
        before = len(self.ctx.repos.categories.by_store(self.ids["store_a"]))
        self.view.new_category.set("")
        self.click(self.view, "新增分类")
        self.assertEqual(len(self.ctx.repos.categories.by_store(self.ids["store_a"])), before)
        self.view.new_category.set("汤品")
        self.click(self.view, "新增分类")
        self.assertEqual(len(self.ctx.repos.categories.by_store(self.ids["store_a"])), before + 1)

    def test_add_dish_valid_and_invalid_stock(self) -> None:
        before = len(self.ctx.repos.dishes.by_store(self.ids["store_a"]))
        self.view.dish_name.set("酸辣汤")
        self.view.dish_price.set("12.00")
        self.view.dish_stock.set("-3")
        self.view.dish_desc.set("酸辣")
        self.click(self.view, "添加菜品")
        self.assertEqual(len(self.ctx.repos.dishes.by_store(self.ids["store_a"])), before)
        self.view.dish_stock.set("8")
        self.click(self.view, "添加菜品")
        self.assertEqual(len(self.ctx.repos.dishes.by_store(self.ids["store_a"])), before + 1)

    def test_add_dish_rejects_bad_price_as_business_error(self) -> None:
        before = len(self.ctx.repos.dishes.by_store(self.ids["store_a"]))
        self.view.dish_name.set("黑暗料理")
        self.view.dish_price.set("免费")
        self.view.dish_stock.set("5")
        self.click(self.view, "添加菜品")
        self.assertEqual(len(self.ctx.repos.dishes.by_store(self.ids["store_a"])), before)
        self.assertTrue(
            any(title == "操作失败" for kind, title, _ in self.calls if kind == "error")
        )

    def test_dish_buttons_without_selection_prompt(self) -> None:
        self.clear_selection(self.view.dish_tree)
        self.click(self.view, "修改菜品")
        self.click(self.view, "上架")
        self.click(self.view, "下架")
        self.assertGreaterEqual(len(self.messages("info")), 3)

    def test_dish_off_shelf_and_on_shelf(self) -> None:
        self.select(self.view.dish_tree, self.ids["dish_a_hot"])
        self.click(self.view, "下架")
        self.assertIs(
            self.ctx.repos.dishes.get(self.ids["dish_a_hot"]).status, DishStatus.OFF_SHELF
        )
        self.select(self.view.dish_tree, self.ids["dish_a_hot"])
        self.click(self.view, "上架")
        self.assertIs(
            self.ctx.repos.dishes.get(self.ids["dish_a_hot"]).status, DishStatus.ON_SALE
        )

    def test_edit_dish_button_opens_dialog_without_error(self) -> None:
        self.select(self.view.dish_tree, self.ids["dish_a_hot"])
        self.click(self.view, "修改菜品")

    def test_order_accept_and_mark_ready(self) -> None:
        order = self.place()
        self.ctx.orders.pay(order.order_id, self.customer_id())
        self.view.safe_refresh()
        self.select(self.view.merchant_order_tree, order.order_id)
        self.click(self.view, "接单")
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.PREPARING)
        self.select(self.view.merchant_order_tree, order.order_id)
        self.click(self.view, "标记出餐")
        self.assertIs(
            self.ctx.repos.orders.get(order.order_id).status, OrderStatus.PENDING_DELIVERY
        )
        self.assertIsNotNone(self.ctx.repos.deliveries.by_order(order.order_id))

    def customer_id(self) -> str:
        return self.ids["customer"]

    def test_order_reject_refunds(self) -> None:
        order = self.place()
        self.ctx.orders.pay(order.order_id, self.customer_id())
        self.view.safe_refresh()
        self.select(self.view.merchant_order_tree, order.order_id)
        self.click(self.view, "拒单")
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.CANCELLED)
        payment = self.ctx.payments.payment_of(order.order_id)
        assert payment is not None
        self.assertIs(payment.status, PaymentStatus.REFUNDED)

    def test_order_buttons_without_selection_prompt(self) -> None:
        self.clear_selection(self.view.merchant_order_tree)
        self.click(self.view, "接单")
        self.click(self.view, "拒单")
        self.click(self.view, "标记出餐")
        self.assertGreaterEqual(len(self.messages("info")), 3)

    def _pending_refund(self):
        order, _task = self.delivering_order()
        refund = self.ctx.refunds.apply(order.order_id, self.ids["customer"], "餐品撒漏")
        self.view.safe_refresh()
        self.select(self.view.refund_tree, refund.refund_id)
        return order, refund

    def test_refund_approve_button(self) -> None:
        order, refund = self._pending_refund()
        self.askstring_value = "同意退款"
        self.click(self.view, "同意退款")
        self.assertIs(self.ctx.repos.refunds.get(refund.refund_id).status, RefundStatus.APPROVED)
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.REFUNDED)

    def test_refund_reject_button(self) -> None:
        order, refund = self._pending_refund()
        self.askstring_value = "已出餐"
        self.click(self.view, "驳回")
        self.assertIs(self.ctx.repos.refunds.get(refund.refund_id).status, RefundStatus.REJECTED)
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.DELIVERING)

    def test_refund_without_selection_prompts(self) -> None:
        self.clear_selection(self.view.refund_tree)
        self.click(self.view, "同意退款")
        self.click(self.view, "驳回")
        self.assertGreaterEqual(len(self.messages("info")), 2)

    def test_message_mark_all_read(self) -> None:
        self.ctx.notifications.send(self.merchant, "新订单", "请及时处理")
        self.view.safe_refresh()
        self.click(self.view.message_panel, "全部标为已读")
        self.assertEqual(self.ctx.notifications.unread_count(self.merchant), 0)

    def test_apply_store_for_new_merchant(self) -> None:
        self.ctx.auth.register("13911112222", "新商家", UserRole.MERCHANT, DEMO_CODE)
        view = self.login_as("13911112222")
        assert isinstance(view, MerchantView)
        view.reg_name.set("夜宵档")
        view.reg_address.set("学府路 40 号")
        view.reg_x.set("0.6")
        view.reg_y.set("0.2")
        view.reg_min.set("12")
        self.click(view, "提交入驻申请")
        store = self.ctx.stores.store_of_merchant(self.app.user.user_id)
        assert store is not None
        self.assertIs(store.status, StoreStatus.PENDING)
        self.assertFalse(self.find_widget(view, "开始营业").instate(["!disabled"]))

    def test_apply_store_rejects_bad_coordinates(self) -> None:
        self.ctx.auth.register("13911113333", "新商家二", UserRole.MERCHANT, DEMO_CODE)
        view = self.login_as("13911113333")
        view.reg_x.set("东经")
        self.click(view, "提交入驻申请")
        self.assertIsNone(self.ctx.stores.store_of_merchant(self.app.user.user_id))
        self.assertTrue(any("坐标" in message for _k, _t, message in self.messages("info")))


# ====================================================================== #
# 骑手端
# ====================================================================== #
class RiderViewTest(UiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.view = self.login_as("13700000001")
        assert isinstance(self.view, RiderView)
        self.rider = self.ids["rider"]

    def test_toggle_online_button(self) -> None:
        self.click(self.view, "下线休息")
        self.assertFalse(self.ctx.repos.users.get(self.rider).online)
        self.click(self.view, "上线接单")
        self.assertTrue(self.ctx.repos.users.get(self.rider).online)

    def test_grab_requires_selection(self) -> None:
        self.clear_selection(self.view.hall_tree)
        self.click(self.view, "抢单")
        self.assertTrue(any("配送单" in message for _k, _t, message in self.messages("info")))

    def test_grab_pickup_deliver_buttons(self) -> None:
        _order, task = self.ready_order()
        self.view.safe_refresh()
        self.select(self.view.hall_tree, task.task_id)
        self.click(self.view, "抢单")
        self.assertIs(self.ctx.repos.deliveries.get(task.task_id).status, DeliveryStatus.GRABBED)

        self.view.safe_refresh()
        self.select(self.view.mine_tree, task.task_id)
        self.click(self.view, "确认取餐")
        self.assertIs(self.ctx.repos.deliveries.get(task.task_id).status, DeliveryStatus.PICKED)

        self.view.safe_refresh()
        self.select(self.view.mine_tree, task.task_id)
        self.click(self.view, "确认送达")
        self.assertIs(self.ctx.repos.deliveries.get(task.task_id).status, DeliveryStatus.DELIVERED)

    def test_mytask_buttons_require_selection(self) -> None:
        self.clear_selection(self.view.mine_tree)
        self.click(self.view, "确认取餐")
        self.click(self.view, "确认送达")
        self.click(self.view, "上报异常")
        self.assertGreaterEqual(len(self.messages("info")), 3)

    def test_report_exception_button(self) -> None:
        _order, task = self.ready_order()
        self.ctx.delivery.grab(task.task_id, self.rider)
        self.ctx.delivery.pickup(task.task_id, self.rider)
        self.dialog_results[ChoiceDialog] = "联系不上顾客"
        self.view.safe_refresh()
        self.select(self.view.mine_tree, task.task_id)
        self.click(self.view, "上报异常")
        failed = self.ctx.repos.orders.get(task.order_id)
        self.assertIs(failed.status, OrderStatus.DELIVERY_FAILED)
        self.assertEqual(
            self.ctx.repos.deliveries.get(task.task_id).exception_reason, "联系不上顾客"
        )

    def test_message_mark_all_read(self) -> None:
        self.ctx.notifications.send(self.rider, "派单提醒", "附近有新订单")
        self.view.safe_refresh()
        self.click(self.view.message_panel, "全部标为已读")
        self.assertEqual(self.ctx.notifications.unread_count(self.rider), 0)


# ====================================================================== #
# 管理员端
# ====================================================================== #
class AdminViewTest(UiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.view = self.login_as("13600000001")
        assert isinstance(self.view, AdminView)
        self.admin = self.ids["admin"]

    def test_approve_store_button(self) -> None:
        merchant_id = self.new_merchant_with_pending_store()
        store = self.ctx.stores.store_of_merchant(merchant_id)
        assert store is not None
        self.view.safe_refresh()
        self.select(self.view.pending_store_tree, store.store_id)
        self.click(self.view, "审核通过")
        self.assertIs(self.ctx.repos.stores.get(store.store_id).status, StoreStatus.OPEN)

    def test_reject_store_button(self) -> None:
        merchant_id = self.new_merchant_with_pending_store()
        store = self.ctx.stores.store_of_merchant(merchant_id)
        assert store is not None
        self.dialog_results[TextDialog] = "资料不全"
        self.view.safe_refresh()
        self.select(self.view.pending_store_tree, store.store_id)
        self.click(self.view, "驳回申请")
        self.assertIs(self.ctx.repos.stores.get(store.store_id).status, StoreStatus.REJECTED)

    def test_suspend_and_restore_store_buttons(self) -> None:
        self.dialog_results[TextDialog] = "违规经营"
        self.view.safe_refresh()
        self.select(self.view.all_store_tree, self.ids["store_a"])
        self.click(self.view, "关停店铺")
        self.assertIs(
            self.ctx.repos.stores.get(self.ids["store_a"]).status, StoreStatus.SUSPENDED
        )
        self.view.safe_refresh()
        self.select(self.view.all_store_tree, self.ids["store_a"])
        self.click(self.view, "解除关停")
        self.assertIs(self.ctx.repos.stores.get(self.ids["store_a"]).status, StoreStatus.CLOSED)

    def test_store_buttons_without_selection_prompt(self) -> None:
        self.clear_selection(self.view.pending_store_tree)
        self.clear_selection(self.view.all_store_tree)
        self.click(self.view, "审核通过")
        self.click(self.view, "驳回申请")
        self.click(self.view, "关停店铺")
        self.click(self.view, "解除关停")
        self.assertGreaterEqual(len(self.messages("info")), 4)

    def _pending_refund(self):
        order, _task = self.delivering_order()
        refund = self.ctx.refunds.apply(order.order_id, self.ids["customer"], "餐品撒漏")
        self.view.safe_refresh()
        self.select(self.view.refund_tree, refund.refund_id)
        return order, refund

    def test_arbitrate_approve_button(self) -> None:
        order, refund = self._pending_refund()
        self.dialog_results[ArbitrationDialog] = (
            True,
            ResponsibleParty.MERCHANT,
            "商家出餐错误",
        )
        self.click(self.view, "仲裁处理")
        self.assertIs(
            self.ctx.repos.refunds.get(refund.refund_id).status, RefundStatus.ARBITRATED
        )
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.REFUNDED)

    def test_arbitrate_reject_button(self) -> None:
        order, refund = self._pending_refund()
        self.dialog_results[ArbitrationDialog] = (
            False,
            ResponsibleParty.CUSTOMER,
            "顾客原因",
        )
        self.click(self.view, "仲裁处理")
        self.assertIs(self.ctx.repos.refunds.get(refund.refund_id).status, RefundStatus.REJECTED)
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.DELIVERING)

    def test_arbitrate_without_selection_prompts(self) -> None:
        self.clear_selection(self.view.refund_tree)
        self.click(self.view, "仲裁处理")
        self.assertTrue(self.messages("info"))

    def test_redispatch_button(self) -> None:
        order, _task = self.failed_order()
        self.view.safe_refresh()
        self.select(self.view.failed_tree, order.order_id)
        self.click(self.view, "重新派单")
        new_task = self.ctx.repos.deliveries.by_order(order.order_id)
        assert new_task is not None
        self.assertEqual(new_task.dispatch_round, 2)
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.DELIVERING)

    def test_redispatch_without_rider_prompts(self) -> None:
        order, _task = self.failed_order()
        for rider in self.ctx.repos.users.riders():
            self.ctx.delivery.set_online(rider.user_id, False)
        self.view.safe_refresh()
        self.select(self.view.failed_tree, order.order_id)
        self.click(self.view, "重新派单")
        self.assertTrue(
            any("骑手" in message for _k, _t, message in self.messages("info"))
        )

    def test_freeze_and_unfreeze_buttons(self) -> None:
        customer = self.ids["customer"]
        self.dialog_results[TextDialog] = "恶意下单"
        self.view.safe_refresh()
        self.select(self.view.user_tree, customer)
        self.click(self.view, "冻结账号")
        self.assertIs(self.ctx.repos.users.get(customer).status, AccountStatus.FROZEN)
        self.view.safe_refresh()
        self.select(self.view.user_tree, customer)
        self.click(self.view, "解除冻结")
        self.assertIs(self.ctx.repos.users.get(customer).status, AccountStatus.ACTIVE)

    def test_freeze_without_selection_prompts(self) -> None:
        self.clear_selection(self.view.user_tree)
        self.click(self.view, "冻结账号")
        self.click(self.view, "解除冻结")
        self.assertGreaterEqual(len(self.messages("info")), 2)

    def test_role_filter_limits_user_list(self) -> None:
        self.view.role_filter.set(UserRole.RIDER.label)
        self.view.role_filter.event_generate("<<ComboboxSelected>>")
        self.app.update()
        self.assert_clean()
        rows = self.view.user_tree.get_children()
        self.assertTrue(rows)
        for row in rows:
            user = self.ctx.repos.users.get(row)
            self.assertIs(user.role, UserRole.RIDER)

    def test_audit_query_button(self) -> None:
        self.view.audit_keyword.set(self.admin)
        self.click(self.view, "查询")
        self.assertTrue(self.view.audit_tree.get_children())
        self.view.audit_keyword.set("不存在的编号")
        self.click(self.view, "查询")
        self.assertEqual(self.view.audit_tree.get_children(), ())


# ====================================================================== #
# 模态对话框自身按钮
# ====================================================================== #
class DialogButtonTest(UiTestCase):
    def test_choice_dialog_submit_and_cancel(self) -> None:
        dialog = ChoiceDialog(self.app, "拒单原因", ["缺货", "打烊"])
        self.assertEqual(dialog.value.get(), "缺货")
        dialog.value.set("打烊")
        dialog._submit()  # pylint: disable=protected-access
        self.assertEqual(dialog.result, "打烊")
        self.assertFalse(dialog.winfo_exists())

        empty = ChoiceDialog(self.app, "空选项", [])
        empty._submit()  # pylint: disable=protected-access
        self.assertIsNone(empty.result)
        self.assertTrue(empty.winfo_exists())
        empty.destroy()

    def test_text_dialog_accepts_blank_and_text(self) -> None:
        dialog = TextDialog(self.app, "关停", "请输入原因")
        dialog._submit()  # pylint: disable=protected-access
        self.assertEqual(dialog.result, "")
        dialog2 = TextDialog(self.app, "关停", "请输入原因")
        dialog2.value.set("  违规  ")
        dialog2._submit()  # pylint: disable=protected-access
        self.assertEqual(dialog2.result, "违规")

    def test_arbitration_dialog_requires_conclusion(self) -> None:
        dialog = ArbitrationDialog(self.app)
        dialog._submit()  # pylint: disable=protected-access
        self.assertIsNone(dialog.result)
        self.assertTrue(dialog.winfo_exists())
        dialog.conclusion_var.set("商家责任")
        dialog.approve_var.set("reject")
        dialog.party_var.set(ResponsibleParty.CUSTOMER.label)
        dialog._submit()  # pylint: disable=protected-access
        approve, party, conclusion = dialog.result
        self.assertFalse(approve)
        self.assertIs(party, ResponsibleParty.CUSTOMER)
        self.assertEqual(conclusion, "商家责任")

    def test_review_dialog_submits_rating_and_text(self) -> None:
        dialog = ReviewDialog(self.app, "ORD-0001")
        dialog.rating.set("4")
        dialog.text.insert("1.0", "送得很快")
        dialog._submit()  # pylint: disable=protected-access
        self.assertEqual(dialog.result, (4, "送得很快"))

    def test_edit_dish_dialog_saves_and_validates(self) -> None:
        merchant = self.ids["merchant_a"]
        dish_id = self.ids["dish_a_hot"]
        dialog = EditDishDialog(self.app, self.ctx, merchant, dish_id)
        dialog.stock.set("abc")
        dialog._save()  # pylint: disable=protected-access
        self.assertTrue(dialog.winfo_exists())
        dialog.stock.set("12")
        dialog.price.set("30.00")
        dialog._save()  # pylint: disable=protected-access
        self.assertTrue(dialog.result)
        dish = self.ctx.repos.dishes.get(dish_id)
        self.assertEqual(dish.stock, 12)
        self.assertEqual(str(dish.price), "30.00")


if __name__ == "__main__":
    unittest.main()
