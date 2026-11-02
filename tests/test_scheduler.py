"""定时任务测试：超时取消、退款自动同意、派单升级与自动收货。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.config import Settings
from app.container import AppContext, build_context
from app.domain.enums import DeliveryStatus, OrderStatus, RefundStatus
from app.jobs.scheduler import Scheduler
from app.seed import seed_demo_data


class SchedulerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self._tmp.name))
        self.ctx: AppContext = build_context(self.settings)
        self.ids = seed_demo_data(self.ctx)
        self.customer = self.ids["customer"]
        self.address = self.ctx.users.default_address(self.customer)
        assert self.address is not None
        self.now = datetime(2026, 11, 2, 12, 0, 0)
        self.scheduler = Scheduler(self.ctx)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def place(self):
        self.ctx.cart.add_item(self.customer, self.ids["dish_a_hot"], 1)
        return self.ctx.orders.checkout(
            self.customer, self.address.address_id, now=self.now
        ).order

    def test_unpaid_order_cancelled_after_timeout(self) -> None:
        order = self.place()
        later = self.now + timedelta(minutes=16)
        report = self.scheduler.tick(later)
        self.assertEqual(report.cancelled_unpaid, 1)
        self.assertIs(
            self.ctx.repos.orders.get(order.order_id).status, OrderStatus.CANCELLED
        )
        self.assertEqual(self.ctx.repos.dishes.get(self.ids["dish_a_hot"]).stock, 30)

    def test_accept_timeout_auto_cancels_and_refunds(self) -> None:
        order = self.place()
        self.ctx.orders.pay(order.order_id, self.customer, now=self.now)
        later = self.now + timedelta(minutes=11)
        report = self.scheduler.tick(later)
        self.assertEqual(report.cancelled_accept_timeout, 1)
        self.assertIs(
            self.ctx.repos.orders.get(order.order_id).status, OrderStatus.CANCELLED
        )

    def test_refund_auto_approved_after_deadline(self) -> None:
        order = self.place()
        self.ctx.orders.pay(order.order_id, self.customer, now=self.now)
        self.ctx.orders.merchant_accept(order.order_id, self.ids["merchant_a"], now=self.now)
        refund = self.ctx.refunds.apply(order.order_id, self.customer, "餐品撒漏", now=self.now)
        later = self.now + timedelta(minutes=11)
        report = self.scheduler.tick(later)
        self.assertEqual(report.refunds_auto_approved, 1)
        self.assertIs(
            self.ctx.repos.refunds.get(refund.refund_id).status,
            RefundStatus.AUTO_APPROVED,
        )
        self.assertIs(
            self.ctx.repos.orders.get(order.order_id).status, OrderStatus.REFUNDED
        )

    def test_dispatch_escalates_then_becomes_manual(self) -> None:
        order = self.place()
        self.ctx.orders.pay(order.order_id, self.customer, now=self.now)
        self.ctx.orders.merchant_accept(order.order_id, self.ids["merchant_a"], now=self.now)
        self.ctx.orders.mark_ready(order.order_id, self.ids["merchant_a"], now=self.now)
        task = self.ctx.repos.deliveries.by_order(order.order_id)
        assert task is not None

        current = self.now
        for _ in range(self.settings.dispatch_max_rounds):
            current += timedelta(minutes=4)
            self.scheduler.tick(current)
        escalated = self.ctx.repos.deliveries.get(task.task_id)
        self.assertIs(escalated.status, DeliveryStatus.MANUAL)
        self.assertIs(
            self.ctx.repos.orders.get(order.order_id).status, OrderStatus.PENDING_DELIVERY
        )

    def test_delivered_order_auto_completes_after_24h(self) -> None:
        order = self.place()
        self.ctx.orders.pay(order.order_id, self.customer, now=self.now)
        self.ctx.orders.merchant_accept(order.order_id, self.ids["merchant_a"], now=self.now)
        self.ctx.orders.mark_ready(order.order_id, self.ids["merchant_a"], now=self.now)
        task = self.ctx.repos.deliveries.by_order(order.order_id)
        assert task is not None
        self.ctx.delivery.grab(task.task_id, self.ids["rider"], now=self.now)
        self.ctx.delivery.pickup(task.task_id, self.ids["rider"], now=self.now)
        self.ctx.delivery.deliver(task.task_id, self.ids["rider"], now=self.now)

        report = self.scheduler.tick(self.now + timedelta(hours=25))
        self.assertEqual(report.auto_completed, 1)
        self.assertIs(
            self.ctx.repos.orders.get(order.order_id).status, OrderStatus.COMPLETED
        )

    def test_tick_is_noop_when_nothing_due(self) -> None:
        self.place()
        report = self.scheduler.tick(self.now + timedelta(minutes=1))
        self.assertEqual(report.changed, 0)


if __name__ == "__main__":
    unittest.main()
