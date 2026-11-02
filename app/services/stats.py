"""经营统计与平台看板（REQ-013）。

营业额只统计已完成订单；退款订单不计入。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.domain.enums import OrderStatus, RefundStatus
from app.repository.repositories import Repositories
from app.services.base import BaseService


@dataclass(frozen=True)
class MerchantStats:
    order_count: int
    completed_count: int
    revenue: Decimal
    refund_count: int
    timeout_count: int
    rating: float


@dataclass(frozen=True)
class StoreRanking:
    store_id: str
    name: str
    revenue: Decimal
    orders: int


@dataclass(frozen=True)
class PlatformStats:
    total_orders: int
    completed_orders: int
    gmv: Decimal
    refund_orders: int
    customers: int
    merchants: int
    riders: int
    active_stores: int
    ranking: list[StoreRanking]


class StatsService(BaseService):
    def __init__(self, repos: Repositories, settings) -> None:
        super().__init__(repos, settings)

    def merchant_stats(
        self, merchant_id: str, *, day: date | None = None
    ) -> MerchantStats:
        self.require_merchant(merchant_id)
        store = self.repos.stores.by_merchant(merchant_id)
        if store is None:
            return MerchantStats(0, 0, Decimal("0.00"), 0, 0, 5.0)
        orders = self.repos.orders.by_store(store.store_id)
        refunds = self.repos.refunds.by_store(store.store_id)
        if day is not None:
            orders = [o for o in orders if o.created_at.date() == day]
            refunds = [r for r in refunds if r.created_at.date() == day]
        completed = [o for o in orders if o.status is OrderStatus.COMPLETED]
        refunded = [
            r
            for r in refunds
            if r.status
            in (
                RefundStatus.APPROVED,
                RefundStatus.AUTO_APPROVED,
                RefundStatus.ARBITRATED,
            )
        ]
        merchant = self.get_user(merchant_id)
        return MerchantStats(
            order_count=len(orders),
            completed_count=len(completed),
            revenue=sum((o.payable_amount for o in completed), Decimal("0.00")),
            refund_count=len(refunded),
            timeout_count=getattr(merchant, "timeout_count", 0),
            rating=store.rating,
        )

    def platform_stats(self, admin_id: str, *, day: date | None = None) -> PlatformStats:
        self.require_admin(admin_id)
        orders = self.repos.orders.all()
        if day is not None:
            orders = [o for o in orders if o.created_at.date() == day]
        completed = [o for o in orders if o.status is OrderStatus.COMPLETED]
        refunded = [o for o in orders if o.status is OrderStatus.REFUNDED]

        ranking: list[StoreRanking] = []
        for store in self.repos.stores.all():
            store_orders = [o for o in completed if o.store_id == store.store_id]
            ranking.append(
                StoreRanking(
                    store_id=store.store_id,
                    name=store.name,
                    revenue=sum((o.payable_amount for o in store_orders), Decimal("0.00")),
                    orders=len(store_orders),
                )
            )
        ranking.sort(key=lambda item: item.revenue, reverse=True)

        return PlatformStats(
            total_orders=len(orders),
            completed_orders=len(completed),
            gmv=sum((o.payable_amount for o in completed), Decimal("0.00")),
            refund_orders=len(refunded),
            customers=len(self.repos.users.customers()),
            merchants=len(self.repos.users.merchants()),
            riders=len(self.repos.users.riders()),
            active_stores=sum(1 for s in self.repos.stores.all() if s.is_open),
            ranking=ranking,
        )

    def orders_by_status(self) -> dict[str, int]:
        buckets: dict[str, int] = {}
        for order in self.repos.orders.all():
            buckets[order.status.label] = buckets.get(order.status.label, 0) + 1
        return buckets

    def today(self) -> date:
        return datetime.now().date()
