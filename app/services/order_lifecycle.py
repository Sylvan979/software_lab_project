"""订单状态迁移的统一入口。

所有服务都必须通过 ``OrderLifecycle.transition`` 改状态：
这样时间戳、状态流水、审计日志只写一处，避免多处实现产生不一致。
"""

from __future__ import annotations

from datetime import datetime

from app.domain.enums import OrderStatus, UserRole
from app.domain.models import Order, StatusChange
from app.domain.state_machine import OrderStateMachine
from app.repository.repositories import Repositories
from app.services.audit import AuditService
from app.services.base import BaseService
from app.services.notifications import NotificationService


class OrderLifecycle(BaseService):
    def __init__(
        self,
        repos: Repositories,
        settings,
        audit: AuditService,
        notifications: NotificationService,
    ) -> None:
        super().__init__(repos, settings)
        self.audit = audit
        self.notifications = notifications

    def transition(
        self,
        order: Order,
        target: OrderStatus,
        *,
        actor_id: str,
        actor_role: UserRole | str,
        note: str = "",
        now: datetime | None = None,
    ) -> Order:
        now = now or datetime.now()
        source = order.status
        OrderStateMachine.assert_transition(source, target)

        order.status = target
        self._stamp(order, target, now)
        role_text = actor_role.label if isinstance(actor_role, UserRole) else str(actor_role)
        order.status_history.append(
            StatusChange(
                status=target,
                changed_at=now,
                actor_id=actor_id,
                actor_role=role_text,
                note=note,
            )
        )
        self.repos.orders.update(order)
        self.audit.record(
            actor_id=actor_id,
            actor_role=role_text,
            action="订单状态变更",
            target_type="订单",
            target_id=order.order_id,
            detail=f"{source.label} → {target.label}" + (f"：{note}" if note else ""),
        )
        return order

    @staticmethod
    def _stamp(order: Order, target: OrderStatus, now: datetime) -> None:
        stamps = {
            OrderStatus.PREPARING: "accepted_at",
            OrderStatus.PENDING_DELIVERY: "ready_at",
            OrderStatus.DELIVERED: "delivered_at",
            OrderStatus.COMPLETED: "completed_at",
            OrderStatus.CANCELLED: "cancelled_at",
            OrderStatus.REFUNDED: "refunded_at",
        }
        attribute = stamps.get(target)
        if attribute:
            setattr(order, attribute, now)

    def release_stock(self, order: Order) -> None:
        """释放下单时预占的库存；已送达的订单不回收（餐品已消耗）。"""
        if order.stock_released or order.delivered_at is not None:
            return
        for item in order.items:
            dish = self.repos.dishes.find(item.dish_id)
            if dish is not None:
                dish.restore_stock(item.quantity)
                self.repos.dishes.update(dish)
        order.stock_released = True
        self.repos.orders.update(order)

    def notify(self, user_ids: list[str], title: str, body: str) -> None:
        self.notifications.send_many(user_ids, title, body)
