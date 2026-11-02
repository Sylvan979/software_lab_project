"""服务层流程测试：下单、支付、配送、退款、超时与权限。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.config import Settings
from app.container import AppContext, build_context
from app.domain.enums import DeliveryStatus, OrderStatus, PaymentStatus, RefundStatus
from app.exceptions import (
    AuthenticationError,
    ConflictError,
    OutOfRangeError,
    PermissionDeniedError,
)
from app.seed import DEMO_CODE, seed_demo_data


class ServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        settings = Settings(data_dir=Path(self._tmp.name))
        self.ctx: AppContext = build_context(settings)
        self.ids = seed_demo_data(self.ctx)
        self.customer = self.ids["customer"]
        self.address = self.ctx.users.default_address(self.customer)
        assert self.address is not None
        self.now = datetime(2026, 11, 2, 12, 0, 0)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ------------------------------------------------------------------ #
    def place(self, dish_key: str = "dish_a_hot", qty: int = 1, key: str | None = None):
        self.ctx.cart.add_item(self.customer, self.ids[dish_key], qty)
        return self.ctx.orders.checkout(
            self.customer,
            self.address.address_id,
            idempotency_key=key,
            now=self.now,
        ).order

    def pay_and_accept(self, order_id: str):
        self.ctx.orders.pay(order_id, self.customer, now=self.now)
        self.ctx.orders.merchant_accept(order_id, self.ids["merchant_a"], now=self.now)
        self.ctx.orders.mark_ready(order_id, self.ids["merchant_a"], now=self.now)
        task = self.ctx.repos.deliveries.by_order(order_id)
        assert task is not None
        self.ctx.delivery.grab(task.task_id, self.ids["rider"], now=self.now)
        self.ctx.delivery.pickup(task.task_id, self.ids["rider"], now=self.now)
        return task


class OrderFlowTest(ServiceTestCase):
    def test_happy_path_records_history_and_review(self) -> None:
        order = self.place(qty=2)
        self.assertIs(order.status, OrderStatus.PENDING_PAYMENT)
        stock_after_order = self.ctx.repos.dishes.get(self.ids["dish_a_hot"]).stock

        self.ctx.orders.pay(order.order_id, self.customer, now=self.now)
        self.ctx.orders.merchant_accept(order.order_id, self.ids["merchant_a"], now=self.now)
        self.ctx.orders.mark_ready(order.order_id, self.ids["merchant_a"], now=self.now)
        task = self.ctx.repos.deliveries.by_order(order.order_id)
        assert task is not None
        self.ctx.delivery.grab(task.task_id, self.ids["rider"], now=self.now)
        picked = self.ctx.delivery.pickup(task.task_id, self.ids["rider"], now=self.now)
        self.assertIs(picked.status, DeliveryStatus.PICKED)
        self.ctx.delivery.deliver(task.task_id, self.ids["rider"], now=self.now)
        self.ctx.orders.confirm_receipt(order.order_id, self.customer, now=self.now)
        self.ctx.orders.review(order.order_id, self.customer, 5, "好吃")

        final = self.ctx.repos.orders.get(order.order_id)
        self.assertIs(final.status, OrderStatus.COMPLETED)
        self.assertEqual(
            [change.status for change in final.status_history],
            [
                OrderStatus.PENDING_PAYMENT,
                OrderStatus.PENDING_ACCEPTANCE,
                OrderStatus.PREPARING,
                OrderStatus.PENDING_DELIVERY,
                OrderStatus.DELIVERING,
                OrderStatus.DELIVERED,
                OrderStatus.COMPLETED,
            ],
        )
        self.assertEqual(stock_after_order, 28)
        store = self.ctx.repos.stores.get(self.ids["store_a"])
        self.assertEqual(store.rating, 5.0)
        self.assertEqual(store.rating_count, 1)
        with self.assertRaises(ConflictError):
            self.ctx.orders.review(order.order_id, self.customer, 4, "重复评价")

    def test_idempotent_checkout_returns_same_order(self) -> None:
        first = self.place(key="idem-1")
        second = self.place(qty=1, key="idem-1")
        self.assertEqual(first.order_id, second.order_id)
        self.assertEqual(self.ctx.repos.orders.count(), 1)

    def test_payment_failure_cancels_and_restores_stock(self) -> None:
        before = self.ctx.repos.dishes.get(self.ids["dish_a_hot"]).stock
        order = self.place(qty=3)
        self.assertEqual(self.ctx.repos.dishes.get(self.ids["dish_a_hot"]).stock, before - 3)
        self.ctx.orders.pay(order.order_id, self.customer, success=False, now=self.now)

        cancelled = self.ctx.repos.orders.get(order.order_id)
        self.assertIs(cancelled.status, OrderStatus.CANCELLED)
        self.assertEqual(cancelled.cancel_reason, "支付失败")
        self.assertEqual(self.ctx.repos.dishes.get(self.ids["dish_a_hot"]).stock, before)
        payment = self.ctx.payments.payment_of(order.order_id)
        assert payment is not None
        self.assertIs(payment.status, PaymentStatus.FAILED)

    def test_out_of_range_address_is_rejected_and_cart_kept(self) -> None:
        far = self.ctx.users.add_address(
            self.customer,
            receiver="陈晓",
            phone="13800000001",
            detail="远郊小区 9 栋 101",
            x_km=9.0,
            y_km=9.0,
        )
        self.ctx.cart.add_item(self.customer, self.ids["dish_a_hot"], 1)
        with self.assertRaises(OutOfRangeError):
            self.ctx.orders.checkout(self.customer, far.address_id, now=self.now)
        self.assertEqual(self.ctx.cart.get_cart(self.customer).total_quantity, 1)
        self.assertEqual(self.ctx.repos.orders.count(), 0)

    def test_merchant_cannot_handle_other_store(self) -> None:
        order = self.place()
        self.ctx.orders.pay(order.order_id, self.customer, now=self.now)
        with self.assertRaises(PermissionDeniedError):
            self.ctx.orders.merchant_accept(order.order_id, self.ids["merchant_b"])

    def test_accept_timeout_refunds_and_counts_merchant(self) -> None:
        order = self.place()
        self.ctx.orders.pay(order.order_id, self.customer, now=self.now)
        later = self.now + timedelta(minutes=11)
        result = self.ctx.orders.handle_accept_timeout(order.order_id, later)
        assert result is not None
        self.assertIs(result.status, OrderStatus.CANCELLED)
        payment = self.ctx.payments.payment_of(order.order_id)
        assert payment is not None
        self.assertIs(payment.status, PaymentStatus.REFUNDED)
        merchant = self.ctx.repos.users.get(self.ids["merchant_a"])
        self.assertEqual(merchant.timeout_count, 1)

    def test_merchant_reject_refunds_full_amount(self) -> None:
        order = self.place()
        self.ctx.orders.pay(order.order_id, self.customer, now=self.now)
        rejected = self.ctx.orders.merchant_reject(
            order.order_id, self.ids["merchant_a"], "缺货", now=self.now
        )
        self.assertIs(rejected.status, OrderStatus.CANCELLED)
        payment = self.ctx.payments.payment_of(order.order_id)
        assert payment is not None
        self.assertIs(payment.status, PaymentStatus.REFUNDED)
        self.assertEqual(payment.amount, rejected.payable_amount)


class RefundAndDeliveryTest(ServiceTestCase):
    def test_refund_approve_marks_order_refunded(self) -> None:
        order = self.place()
        self.pay_and_accept(order.order_id)
        refund = self.ctx.refunds.apply(order.order_id, self.customer, "餐品撒漏")
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.REFUNDING)
        done = self.ctx.refunds.merchant_handle(
            refund.refund_id, self.ids["merchant_a"], approve=True, comment="同意"
        )
        self.assertIs(done.status, RefundStatus.APPROVED)
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.REFUNDED)
        self.assertIs(self.ctx.payments.payment_of(order.order_id).status, PaymentStatus.REFUNDED)
        task = self.ctx.repos.deliveries.find(
            self.ctx.repos.orders.get(order.order_id).delivery_task_id
        )
        self.assertIsNotNone(task)
        self.assertIs(task.status, DeliveryStatus.CANCELLED)
        rider = self.ctx.repos.users.get(self.ids["rider"])
        self.assertNotIn(task.task_id, rider.active_task_ids)
        self.assertEqual(self.ctx.delivery.my_tasks(self.ids["rider"]), [])

    def test_refund_reject_restores_previous_status(self) -> None:
        order = self.place()
        self.ctx.orders.pay(order.order_id, self.customer, now=self.now)
        self.ctx.orders.merchant_accept(order.order_id, self.ids["merchant_a"], now=self.now)
        refund = self.ctx.refunds.apply(order.order_id, self.customer, "不想要了")
        done = self.ctx.refunds.merchant_handle(
            refund.refund_id, self.ids["merchant_a"], approve=False, comment="已出餐"
        )
        self.assertIs(done.status, RefundStatus.REJECTED)
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.PREPARING)
        self.assertIs(self.ctx.payments.payment_of(order.order_id).status, PaymentStatus.PAID)

    def test_duplicate_refund_returns_existing_pending(self) -> None:
        order = self.place()
        self.pay_and_accept(order.order_id)
        first = self.ctx.refunds.apply(order.order_id, self.customer, "餐品撒漏")
        second = self.ctx.refunds.apply(order.order_id, self.customer, "再次申请")
        self.assertEqual(first.refund_id, second.refund_id)
        self.assertEqual(self.ctx.repos.refunds.count(), 1)

    def test_delivery_exception_and_redispatch(self) -> None:
        order = self.place()
        task = self.pay_and_accept(order.order_id)
        self.ctx.delivery.report_exception(
            task.task_id, self.ids["rider"], "联系不上顾客", now=self.now
        )
        failed = self.ctx.repos.orders.get(order.order_id)
        self.assertIs(failed.status, OrderStatus.DELIVERY_FAILED)

        new_task = self.ctx.delivery.redispatch(
            order.order_id, self.ids["admin"], self.ids["rider"], now=self.now
        )
        self.assertNotEqual(new_task.task_id, task.task_id)
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.DELIVERING)
        self.assertEqual(new_task.dispatch_round, 2)

        self.ctx.delivery.pickup(new_task.task_id, self.ids["rider"], now=self.now)
        self.ctx.delivery.deliver(new_task.task_id, self.ids["rider"], now=self.now)
        self.assertIs(self.ctx.repos.orders.get(order.order_id).status, OrderStatus.DELIVERED)

    def test_rider_cannot_deliver_others_task(self) -> None:
        order = self.place()
        task = self.pay_and_accept(order.order_id)
        with self.assertRaises(PermissionDeniedError):
            self.ctx.delivery.deliver(task.task_id, self.ids["customer"])


class AuthTest(ServiceTestCase):
    def test_login_lockout_after_five_failures(self) -> None:
        phone = "13800000001"
        for _ in range(4):
            with self.assertRaises(AuthenticationError):
                self.ctx.auth.login(phone, "000000", now=self.now)
        with self.assertRaises(AuthenticationError):
            self.ctx.auth.login(phone, "000000", now=self.now)
        with self.assertRaises(AuthenticationError):
            self.ctx.auth.login(phone, DEMO_CODE, now=self.now)
        later = self.now + timedelta(minutes=11)
        session = self.ctx.auth.login(phone, DEMO_CODE, now=later)
        self.assertEqual(session.role.value, "customer")

    def test_admin_cannot_self_register(self) -> None:
        from app.domain.enums import UserRole

        with self.assertRaises(PermissionDeniedError):
            self.ctx.auth.register("13500000000", "管理员", UserRole.ADMIN, DEMO_CODE)


if __name__ == "__main__":
    unittest.main()
