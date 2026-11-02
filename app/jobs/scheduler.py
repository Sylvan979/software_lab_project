"""定时任务（对应组件图中的任务调度层）。

每 2 秒由界面定时器驱动一次 ``tick``，扫描所有"没有请求触发也会过期"的业务：
待支付超时、接单超时、退款处理超时、派单超时与送达后自动确认。
任务只调用服务层，不直接改仓储，保证与手工操作走同一套校验。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from app.container import AppContext
from app.domain.enums import OrderStatus
from app.exceptions import DomainError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TickReport:
    cancelled_unpaid: int = 0
    cancelled_accept_timeout: int = 0
    refunds_auto_approved: int = 0
    dispatch_escalated: int = 0
    auto_completed: int = 0

    @property
    def changed(self) -> int:
        return (
            self.cancelled_unpaid
            + self.cancelled_accept_timeout
            + self.refunds_auto_approved
            + self.dispatch_escalated
            + self.auto_completed
        )


class Scheduler:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def tick(self, now: datetime | None = None) -> TickReport:
        now = now or datetime.now()
        cancelled_unpaid = self._safely(
            "处理支付超时", lambda: self._cancel_unpaid(now)
        )
        cancelled_accept = self._safely(
            "处理接单超时", lambda: self._cancel_accept_timeout(now)
        )
        refunds = self._safely(
            "处理退款超时", lambda: self.ctx.refunds.auto_approve_expired(now)
        )
        escalated = self._safely(
            "处理派单超时", lambda: self.ctx.delivery.escalate_stale_tasks(now)
        )
        completed = self._safely("处理自动确认收货", lambda: self._auto_complete(now))
        report = TickReport(
            cancelled_unpaid=cancelled_unpaid,
            cancelled_accept_timeout=cancelled_accept,
            refunds_auto_approved=refunds,
            dispatch_escalated=escalated,
            auto_completed=completed,
        )
        if report.changed:
            logger.info("定时任务：%s", report)
        return report

    def _cancel_unpaid(self, now: datetime) -> int:
        count = 0
        for order in self.ctx.repos.orders.by_status(OrderStatus.PENDING_PAYMENT):
            if self.ctx.orders.handle_payment_timeout(order.order_id, now) is not None:
                count += 1
        return count

    def _cancel_accept_timeout(self, now: datetime) -> int:
        count = 0
        for order in self.ctx.repos.orders.by_status(OrderStatus.PENDING_ACCEPTANCE):
            if self.ctx.orders.handle_accept_timeout(order.order_id, now) is not None:
                count += 1
        return count

    def _auto_complete(self, now: datetime) -> int:
        count = 0
        for order in self.ctx.repos.orders.by_status(OrderStatus.DELIVERED):
            if self.ctx.orders.handle_auto_complete(order.order_id, now) is not None:
                count += 1
        return count

    def _safely(self, name: str, action) -> int:
        """单项任务失败不能拖垮整个调度器。"""
        try:
            return int(action())
        except DomainError as exc:
            logger.warning("%s失败：%s", name, exc)
            for admin in self.ctx.repos.users.admins():
                self.ctx.notifications.send(
                    admin.user_id, f"{name}失败", str(exc)
                )
            return 0
        except Exception:  # noqa: BLE001 - 定时任务必须继续运行
            logger.exception("%s出现未预期异常", name)
            return 0
