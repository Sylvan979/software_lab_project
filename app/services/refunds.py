"""退款与售后仲裁（REQ-012、REQ-016、REQ-021、REQ-022）。

退款单是独立的小状态机：待处理 → 同意 / 驳回 / 超时自动同意 / 平台仲裁。
订单状态与资金流水在同一个事务内变更。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.enums import OrderStatus, RefundStatus, ResponsibleParty, UserRole
from app.domain.models import Order, RefundRequest
from app.exceptions import ConflictError, PermissionDeniedError, ValidationError
from app.repository.repositories import Repositories
from app.services.audit import AuditService
from app.services.base import BaseService
from app.services.notifications import NotificationService
from app.services.order_lifecycle import OrderLifecycle
from app.services.payments import PaymentService

REFUNDABLE_STATUSES = frozenset(
    {
        OrderStatus.PREPARING,
        OrderStatus.PENDING_DELIVERY,
        OrderStatus.DELIVERING,
        OrderStatus.DELIVERY_FAILED,
        OrderStatus.DELIVERED,
    }
)


class RefundService(BaseService):
    def __init__(
        self,
        repos: Repositories,
        settings,
        audit: AuditService,
        notifications: NotificationService,
        lifecycle: OrderLifecycle,
        payments: PaymentService,
    ) -> None:
        super().__init__(repos, settings)
        self.audit = audit
        self.notifications = notifications
        self.lifecycle = lifecycle
        self.payments = payments

    # ------------------------------------------------------------------ #
    # 顾客申请
    # ------------------------------------------------------------------ #
    def apply(
        self,
        order_id: str,
        customer_id: str,
        reason: str,
        *,
        now: datetime | None = None,
    ) -> RefundRequest:
        now = now or datetime.now()
        self.require_customer(customer_id)
        reason = reason.strip()
        if len(reason) < 2:
            raise ValidationError("请填写退款原因（至少 2 个字）")
        with self._lock:
            order = self.repos.orders.get(order_id)
            if order.customer_id != customer_id:
                raise PermissionDeniedError("不能操作他人的订单")
            existing = self.repos.refunds.by_order(order_id)
            if existing is not None:
                if existing.status is RefundStatus.PENDING:
                    return existing
                raise ConflictError("该订单已存在退款记录，不能重复申请")
            if order.status not in REFUNDABLE_STATUSES:
                raise ConflictError(f"订单当前为「{order.status.label}」，不能申请退款")

            refund = RefundRequest(
                refund_id=self.repos.db.next_id("RFD"),
                order_id=order_id,
                customer_id=customer_id,
                store_id=order.store_id,
                amount=order.payable_amount,
                reason=reason,
                status_before_refund=order.status,
                deadline=now + timedelta(minutes=self.settings.refund_timeout_minutes),
            )
            self.repos.refunds.add(refund)
            order.refund_id = refund.refund_id
            order.status_before_refund = order.status
            self.lifecycle.transition(
                order,
                OrderStatus.REFUNDING,
                actor_id=customer_id,
                actor_role=UserRole.CUSTOMER,
                note=f"申请退款：{reason}",
                now=now,
            )
            store = self.repos.stores.get(order.store_id)
            self.notifications.send(
                store.merchant_id,
                "顾客申请退款",
                f"订单 {order.order_id}：{reason}，请在 10 分钟内处理",
            )
            self.notifications.send(customer_id, "退款申请已提交", "商家将在 10 分钟内处理")
            return refund

    # ------------------------------------------------------------------ #
    # 商家处理
    # ------------------------------------------------------------------ #
    def merchant_handle(
        self,
        refund_id: str,
        merchant_id: str,
        *,
        approve: bool,
        comment: str = "",
        now: datetime | None = None,
    ) -> RefundRequest:
        now = now or datetime.now()
        self.require_merchant(merchant_id)
        with self._lock:
            refund = self.repos.refunds.get(refund_id)
            store = self.repos.stores.by_merchant(merchant_id)
            if store is None or refund.store_id != store.store_id:
                raise PermissionDeniedError("不能处理其他店铺的退款申请")
            if refund.status is not RefundStatus.PENDING:
                return refund
            if refund.deadline and now >= refund.deadline:
                return self._complete(
                    refund,
                    RefundStatus.AUTO_APPROVED,
                    handler_id="system",
                    handler_role="系统",
                    comment="超时未处理，系统自动同意",
                    now=now,
                )
            if approve:
                return self._complete(
                    refund,
                    RefundStatus.APPROVED,
                    handler_id=merchant_id,
                    handler_role=UserRole.MERCHANT.label,
                    comment=comment,
                    now=now,
                )
            return self._reject(
                refund,
                handler_id=merchant_id,
                handler_role=UserRole.MERCHANT.label,
                comment=comment,
                now=now,
            )

    # ------------------------------------------------------------------ #
    # 平台仲裁
    # ------------------------------------------------------------------ #
    def admin_arbitrate(
        self,
        refund_id: str,
        admin_id: str,
        *,
        approve: bool,
        responsible_party: ResponsibleParty,
        conclusion: str,
        now: datetime | None = None,
    ) -> RefundRequest:
        now = now or datetime.now()
        admin = self.require_admin(admin_id)
        if not conclusion.strip():
            raise ValidationError("请填写仲裁结论")
        with self._lock:
            refund = self.repos.refunds.get(refund_id)
            if refund.status is not RefundStatus.PENDING:
                raise ConflictError("该退款单已处理，不能重复仲裁")
            if approve:
                refund = self._complete(
                    refund,
                    RefundStatus.ARBITRATED,
                    handler_id=admin.user_id,
                    handler_role=UserRole.ADMIN.label,
                    comment=conclusion.strip(),
                    now=now,
                    responsible_party=responsible_party,
                )
                self.audit.record(
                    actor_id=admin_id,
                    actor_role=admin.role.label,
                    action="仲裁退款",
                    target_type="退款单",
                    target_id=refund_id,
                    detail=f"支持退款；责任方：{responsible_party.label}；{conclusion}",
                )
                return refund
            refund.responsible_party = responsible_party
            refund = self._reject(
                refund,
                handler_id=admin.user_id,
                handler_role=UserRole.ADMIN.label,
                comment=conclusion.strip(),
                now=now,
            )
            self.audit.record(
                actor_id=admin_id,
                actor_role=admin.role.label,
                action="仲裁退款",
                target_type="退款单",
                target_id=refund_id,
                detail=f"驳回退款；责任方：{responsible_party.label}；{conclusion}",
            )
            return refund

    # ------------------------------------------------------------------ #
    # 超时兜底
    # ------------------------------------------------------------------ #
    def auto_approve_expired(self, now: datetime | None = None) -> int:
        now = now or datetime.now()
        count = 0
        for refund in self.repos.refunds.pending():
            if refund.deadline and now >= refund.deadline:
                try:
                    self._complete(
                        refund,
                        RefundStatus.AUTO_APPROVED,
                        handler_id="system",
                        handler_role="系统",
                        comment="超时未处理，系统自动同意",
                        now=now,
                    )
                    count += 1
                except Exception:  # noqa: BLE001 - 资金异常时保持待处理并告警
                    self.notifications.send_many(
                        [admin.user_id for admin in self.repos.users.admins()],
                        "退款执行失败",
                        f"退款单 {refund.refund_id} 需人工处理",
                    )
        return count

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _complete(
        self,
        refund: RefundRequest,
        status: RefundStatus,
        *,
        handler_id: str,
        handler_role: str,
        comment: str,
        now: datetime,
        responsible_party: ResponsibleParty | None = None,
    ) -> RefundRequest:
        order = self.repos.orders.get(refund.order_id)
        self.payments.refund(order, now=now)
        refund.status = status
        refund.handled_at = now
        refund.handler_id = handler_id
        refund.handler_role = handler_role
        refund.comment = comment.strip()
        if responsible_party is not None:
            refund.responsible_party = responsible_party
        self.repos.refunds.update(refund)

        self.lifecycle.transition(
            order,
            OrderStatus.REFUNDED,
            actor_id=handler_id,
            actor_role=handler_role,
            note=f"退款 ¥{refund.amount:.2f}（{status.label}）",
            now=now,
        )
        self.lifecycle.release_stock(order)
        order.status_before_refund = None
        order.refund_id = refund.refund_id
        self.repos.orders.update(order)

        self.notifications.send(
            order.customer_id,
            "退款已到账",
            f"订单 {order.order_id} 已退款 ¥{refund.amount:.2f}",
        )
        self.audit.record(
            actor_id=handler_id,
            actor_role=handler_role,
            action="同意退款",
            target_type="退款单",
            target_id=refund.refund_id,
            detail=f"{order.order_id}，¥{refund.amount:.2f}",
        )
        return refund

    def _reject(
        self,
        refund: RefundRequest,
        *,
        handler_id: str,
        handler_role: str,
        comment: str,
        now: datetime,
    ) -> RefundRequest:
        order = self.repos.orders.get(refund.order_id)
        target = refund.status_before_refund
        refund.status = RefundStatus.REJECTED
        refund.handled_at = now
        refund.handler_id = handler_id
        refund.handler_role = handler_role
        refund.comment = comment.strip()
        self.repos.refunds.update(refund)

        self.lifecycle.transition(
            order,
            target,
            actor_id=handler_id,
            actor_role=handler_role,
            note="退款申请被驳回，订单恢复原状态",
            now=now,
        )
        order.status_before_refund = None
        self.repos.orders.update(order)
        self.notifications.send(
            order.customer_id,
            "退款申请被驳回",
            f"订单 {order.order_id}：" + (comment.strip() or "商家已驳回退款"),
        )
        self.audit.record(
            actor_id=handler_id,
            actor_role=handler_role,
            action="驳回退款",
            target_type="退款单",
            target_id=refund.refund_id,
            detail=comment.strip(),
        )
        return refund

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def for_order(self, order_id: str) -> RefundRequest | None:
        return self.repos.refunds.by_order(order_id)

    def pending_for_store(self, merchant_id: str) -> list[RefundRequest]:
        self.require_merchant(merchant_id)
        store = self.repos.stores.by_merchant(merchant_id)
        if store is None:
            return []
        return [
            r
            for r in self.repos.refunds.by_store(store.store_id)
            if r.status is RefundStatus.PENDING
        ]

    def all_pending(self, admin_id: str) -> list[RefundRequest]:
        self.require_admin(admin_id)
        return self.repos.refunds.pending()
