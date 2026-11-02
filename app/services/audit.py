"""操作日志服务（REQ-014）。

日志只追加，不提供修改与删除方法；查询按时间倒序。
"""

from __future__ import annotations

from app.domain.models import AuditLog
from app.repository.repositories import Repositories
from app.services.base import BaseService


class AuditService(BaseService):
    def record(
        self,
        *,
        actor_id: str,
        actor_role: str,
        action: str,
        target_type: str,
        target_id: str,
        detail: str = "",
        result: str = "成功",
    ) -> AuditLog:
        log = AuditLog(
            log_id=self.repos.db.next_id("LOG"),
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            result=result,
        )
        self.repos.audits.add(log)
        return log

    def query(
        self,
        *,
        actor_id: str | None = None,
        target_id: str | None = None,
        limit: int = 200,
    ) -> list[AuditLog]:
        return self.repos.audits.query(actor_id=actor_id, target_id=target_id, limit=limit)

    def logs_for_store(self, store_id: str, limit: int = 200) -> list[AuditLog]:
        """商家只能查看本店相关日志：按订单号或店铺号过滤。"""
        store_orders = self.repos.orders.by_store(store_id)
        related_ids = {store_id, *(order.order_id for order in store_orders)}
        return [
            log
            for log in self.repos.audits.query(limit=1000)
            if log.target_id in related_ids
        ][:limit]
