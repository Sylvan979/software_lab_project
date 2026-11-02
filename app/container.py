"""依赖装配：按分层顺序构造数据库、仓储、服务。

界面层只依赖 ``AppContext``，替换存储或新增服务时不需要改界面。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import DEFAULT_SETTINGS, Settings
from app.repository.database import JsonDatabase
from app.repository.repositories import Repositories
from app.services.audit import AuditService
from app.services.auth import AuthService
from app.services.cart import CartService
from app.services.delivery import DeliveryService
from app.services.notifications import NotificationService
from app.services.order_lifecycle import OrderLifecycle
from app.services.orders import OrderService
from app.services.payments import PaymentService
from app.services.refunds import RefundService
from app.services.stats import StatsService
from app.services.stores import StoreService
from app.services.users import UserService


@dataclass
class AppContext:
    settings: Settings
    db: JsonDatabase
    repos: Repositories
    audit: AuditService
    notifications: NotificationService
    auth: AuthService
    users: UserService
    stores: StoreService
    cart: CartService
    payments: PaymentService
    lifecycle: OrderLifecycle
    delivery: DeliveryService
    orders: OrderService
    refunds: RefundService
    stats: StatsService


def build_context(settings: Settings | None = None) -> AppContext:
    settings = settings or DEFAULT_SETTINGS
    db = JsonDatabase(settings.db_path(), autosave=settings.autosave)
    repos = Repositories(db)

    audit = AuditService(repos, settings)
    notifications = NotificationService(repos, settings)
    auth = AuthService(repos, settings, audit)
    users = UserService(repos, settings, audit, notifications)
    stores = StoreService(repos, settings, audit, notifications)
    cart = CartService(repos, settings)
    payments = PaymentService(repos, settings, audit)
    lifecycle = OrderLifecycle(repos, settings, audit, notifications)
    delivery = DeliveryService(repos, settings, audit, notifications, lifecycle)
    orders = OrderService(
        repos,
        settings,
        audit,
        notifications,
        lifecycle,
        payments,
        cart,
        delivery,
    )
    refunds = RefundService(
        repos, settings, audit, notifications, lifecycle, payments, delivery
    )
    stats = StatsService(repos, settings)

    return AppContext(
        settings=settings,
        db=db,
        repos=repos,
        audit=audit,
        notifications=notifications,
        auth=auth,
        users=users,
        stores=stores,
        cart=cart,
        payments=payments,
        lifecycle=lifecycle,
        delivery=delivery,
        orders=orders,
        refunds=refunds,
        stats=stats,
    )
