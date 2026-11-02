"""仓储：把领域对象读写细节封装在数据访问层。

服务层只调用仓储方法，不接触 JSON 结构；后续替换为 MySQL/Redis
只需实现同名仓储接口（对应组件图中的数据访问组件）。
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from typing import Any, Generic, TypeVar

from app.domain.enums import (
    DeliveryStatus,
    DishStatus,
    OrderStatus,
    StoreStatus,
)
from app.domain.models import (
    Address,
    Admin,
    AuditLog,
    Cart,
    Category,
    Customer,
    DeliveryTask,
    Dish,
    Merchant,
    Notification,
    Order,
    PaymentRecord,
    RefundRequest,
    Review,
    Rider,
    Store,
    User,
)
from app.exceptions import NotFoundError
from app.repository.codec import decode, encode
from app.repository.database import JsonDatabase

T = TypeVar("T")


class Repository(Generic[T]):
    """通用仓储，负责单表的增删改查与保存。"""

    table_name = ""
    entity_type: type = User

    def __init__(self, db: JsonDatabase) -> None:
        self.db = db
        self._table = db.table(self.table_name)

    def add(self, entity: T) -> T:
        key = self.key_of(entity)
        self._table[key] = encode(entity)
        self.db.mark_dirty()
        return entity

    def update(self, entity: T) -> T:
        return self.add(entity)

    def get(self, entity_id: str) -> T:
        raw = self._table.get(entity_id)
        if raw is None:
            raise NotFoundError(f"未找到记录：{self.table_name}/{entity_id}")
        return decode(raw, self.entity_type)

    def find(self, entity_id: str | None) -> T | None:
        if not entity_id:
            return None
        raw = self._table.get(entity_id)
        return decode(raw, self.entity_type) if raw else None

    def all(self) -> list[T]:
        return [decode(raw, self.entity_type) for raw in self._table.values()]

    def delete(self, entity_id: str) -> None:
        self._table.pop(entity_id, None)
        self.db.mark_dirty()

    def count(self) -> int:
        return len(self._table)

    def key_of(self, entity: T) -> str:
        """按 dataclass 字段声明顺序取第一个非空 ``*_id`` 作为主键。"""
        for f in dataclass_fields(entity):
            if f.name.endswith("_id"):
                value = getattr(entity, f.name, None)
                if value:
                    return str(value)
        raise ValueError(f"{type(entity).__name__} 缺少主键字段")


class UserRepository(Repository[User]):
    table_name = "users"
    entity_type = User

    def find_by_phone(self, phone: str) -> User | None:
        for user in self.all():
            if user.phone == phone:
                return user
        return None

    def customers(self) -> list[Customer]:
        return [u for u in self.all() if isinstance(u, Customer)]

    def merchants(self) -> list[Merchant]:
        return [u for u in self.all() if isinstance(u, Merchant)]

    def riders(self) -> list[Rider]:
        return [u for u in self.all() if isinstance(u, Rider)]

    def admins(self) -> list[Admin]:
        return [u for u in self.all() if isinstance(u, Admin)]


class StoreRepository(Repository[Store]):
    table_name = "stores"
    entity_type = Store

    def by_merchant(self, merchant_id: str) -> Store | None:
        for store in self.all():
            if store.merchant_id == merchant_id:
                return store
        return None

    def open_stores(self) -> list[Store]:
        return [s for s in self.all() if s.status is StoreStatus.OPEN]


class CategoryRepository(Repository[Category]):
    table_name = "categories"
    entity_type = Category

    def by_store(self, store_id: str) -> list[Category]:
        items = [c for c in self.all() if c.store_id == store_id]
        return sorted(items, key=lambda c: (c.sort_no, c.name))


class DishRepository(Repository[Dish]):
    table_name = "dishes"
    entity_type = Dish

    def by_store(self, store_id: str) -> list[Dish]:
        return [d for d in self.all() if d.store_id == store_id]

    def available_by_store(self, store_id: str) -> list[Dish]:
        return [d for d in self.by_store(store_id) if d.is_available]

    def search(self, keyword: str) -> list[Dish]:
        keyword = keyword.strip()
        if not keyword:
            return self.all()
        return [d for d in self.all() if keyword in d.name]


class AddressRepository(Repository[Address]):
    table_name = "addresses"
    entity_type = Address

    def by_customer(self, customer_id: str) -> list[Address]:
        return [a for a in self.all() if a.customer_id == customer_id]


class CartRepository(Repository[Cart]):
    table_name = "carts"
    entity_type = Cart

    def by_customer(self, customer_id: str) -> Cart | None:
        for cart in self.all():
            if cart.customer_id == customer_id:
                return cart
        return None


class OrderRepository(Repository[Order]):
    table_name = "orders"
    entity_type = Order

    def by_customer(self, customer_id: str) -> list[Order]:
        return sorted(
            (o for o in self.all() if o.customer_id == customer_id),
            key=lambda o: o.created_at,
            reverse=True,
        )

    def by_store(self, store_id: str) -> list[Order]:
        return sorted(
            (o for o in self.all() if o.store_id == store_id),
            key=lambda o: o.created_at,
            reverse=True,
        )

    def by_status(self, *statuses: OrderStatus) -> list[Order]:
        wanted = set(statuses)
        return [o for o in self.all() if o.status in wanted]

    def find_by_idempotency(self, customer_id: str, key: str) -> Order | None:
        for order in self.by_customer(customer_id):
            if order.idempotency_key == key:
                return order
        return None


class PaymentRepository(Repository[PaymentRecord]):
    table_name = "payments"
    entity_type = PaymentRecord

    def by_order(self, order_id: str) -> PaymentRecord | None:
        for payment in self.all():
            if payment.order_id == order_id:
                return payment
        return None


class DeliveryRepository(Repository[DeliveryTask]):
    table_name = "deliveries"
    entity_type = DeliveryTask

    def by_order(self, order_id: str) -> DeliveryTask | None:
        for task in self.all():
            if task.order_id == order_id:
                return task
        return None

    def available(self) -> list[DeliveryTask]:
        return [t for t in self.all() if t.status is DeliveryStatus.PENDING]

    def by_rider(self, rider_id: str) -> list[DeliveryTask]:
        return [t for t in self.all() if t.rider_id == rider_id]


class RefundRepository(Repository[RefundRequest]):
    table_name = "refunds"
    entity_type = RefundRequest

    def by_order(self, order_id: str) -> RefundRequest | None:
        for refund in self.all():
            if refund.order_id == order_id:
                return refund
        return None

    def by_store(self, store_id: str) -> list[RefundRequest]:
        return [r for r in self.all() if r.store_id == store_id]

    def pending(self) -> list[RefundRequest]:
        return [r for r in self.all() if r.status.value == "pending"]


class ReviewRepository(Repository[Review]):
    table_name = "reviews"
    entity_type = Review

    def by_order(self, order_id: str) -> Review | None:
        for review in self.all():
            if review.order_id == order_id:
                return review
        return None

    def by_store(self, store_id: str) -> list[Review]:
        return [r for r in self.all() if r.store_id == store_id]


class NotificationRepository(Repository[Notification]):
    table_name = "notifications"
    entity_type = Notification

    def by_user(self, user_id: str) -> list[Notification]:
        return sorted(
            (n for n in self.all() if n.user_id == user_id),
            key=lambda n: n.created_at,
            reverse=True,
        )

    def unread_count(self, user_id: str) -> int:
        return sum(1 for n in self.by_user(user_id) if not n.read)


class AuditRepository(Repository[AuditLog]):
    table_name = "audit_logs"
    entity_type = AuditLog

    def query(
        self,
        *,
        actor_id: str | None = None,
        target_id: str | None = None,
        limit: int = 200,
    ) -> list[AuditLog]:
        logs = [
            log
            for log in reversed(self.all())
            if (actor_id is None or log.actor_id == actor_id)
            and (target_id is None or log.target_id == target_id)
        ]
        return logs[:limit]


class Repositories:
    """仓储集合，作为服务层的唯一数据入口。"""

    def __init__(self, db: JsonDatabase) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.stores = StoreRepository(db)
        self.categories = CategoryRepository(db)
        self.dishes = DishRepository(db)
        self.addresses = AddressRepository(db)
        self.carts = CartRepository(db)
        self.orders = OrderRepository(db)
        self.payments = PaymentRepository(db)
        self.deliveries = DeliveryRepository(db)
        self.refunds = RefundRepository(db)
        self.reviews = ReviewRepository(db)
        self.notifications = NotificationRepository(db)
        self.audits = AuditRepository(db)

    def save(self) -> None:
        self.db.save()

    def transaction(self) -> Any:
        return self.db.transaction()
