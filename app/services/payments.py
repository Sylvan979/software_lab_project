"""模拟支付服务（REQ-016、REQ-024）。

支付与退款都只操作资金流水；订单状态由调用方在同一事务中推进，
任何一步失败都会回滚，避免"已退款但订单仍显示已支付"。
"""

from __future__ import annotations

import secrets
from datetime import datetime

from app.domain.enums import PaymentStatus
from app.domain.models import Order, PaymentRecord
from app.exceptions import ConflictError, PaymentError
from app.repository.repositories import Repositories
from app.services.audit import AuditService
from app.services.base import BaseService


class PaymentService(BaseService):
    def __init__(self, repos: Repositories, settings, audit: AuditService) -> None:
        super().__init__(repos, settings)
        self.audit = audit

    def charge(
        self,
        order: Order,
        *,
        success: bool,
        fail_reason: str = "模拟支付渠道返回失败",
        now: datetime | None = None,
    ) -> PaymentRecord:
        now = now or datetime.now()
        existing = self.repos.payments.by_order(order.order_id)
        if existing and existing.status is PaymentStatus.PAID:
            return existing

        payment = existing or PaymentRecord(
            payment_id=self.repos.db.next_id("PAY"),
            order_id=order.order_id,
            amount=order.payable_amount,
        )
        if success:
            payment.status = PaymentStatus.PAID
            payment.paid_at = now
            payment.transaction_no = "MOCK" + secrets.token_hex(8).upper()
            payment.fail_reason = ""
        else:
            payment.status = PaymentStatus.FAILED
            payment.fail_reason = fail_reason
        self.repos.payments.update(payment)
        self.audit.record(
            actor_id=order.customer_id,
            actor_role="顾客",
            action="模拟支付成功" if success else "模拟支付失败",
            target_type="订单",
            target_id=order.order_id,
            detail=f"{payment.amount:.2f} 元；{payment.transaction_no or fail_reason}",
            result="成功" if success else "失败",
        )
        return payment

    def refund(self, order: Order, *, now: datetime | None = None) -> PaymentRecord:
        payment = self.repos.payments.by_order(order.order_id)
        if payment is None or payment.status is not PaymentStatus.PAID:
            raise PaymentError("该订单没有可退款的支付记录")
        payment.status = PaymentStatus.REFUNDED
        payment.refunded_at = now or datetime.now()
        self.repos.payments.update(payment)
        self.audit.record(
            actor_id="system",
            actor_role="系统",
            action="模拟退款",
            target_type="订单",
            target_id=order.order_id,
            detail=f"退款 {payment.amount:.2f} 元，流水 {payment.transaction_no}",
        )
        return payment

    def payment_of(self, order_id: str) -> PaymentRecord | None:
        return self.repos.payments.by_order(order_id)
