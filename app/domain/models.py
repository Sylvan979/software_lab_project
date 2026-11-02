"""领域模型（与实验二类图一一对应）。

所有实体均为纯数据对象：不依赖仓储、不发起 IO。
单价、数量等参与计算的字段使用 ``Decimal``；金额快照在订单项中固化，
保证商家改价不会影响历史订单（REQ-007）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.domain.enums import (
    AccountStatus,
    DeliveryStatus,
    DishStatus,
    OrderStatus,
    PaymentStatus,
    RefundStatus,
    ResponsibleParty,
    StoreStatus,
    UserRole,
)


def _now() -> datetime:
    return datetime.now()


# --------------------------------------------------------------------------- #
# 用户与权限
# --------------------------------------------------------------------------- #
@dataclass(kw_only=True)
class User:
    user_id: str
    phone: str
    nickname: str
    role: UserRole
    status: AccountStatus = AccountStatus.ACTIVE
    created_at: datetime = field(default_factory=_now)

    @property
    def is_active(self) -> bool:
        return self.status is AccountStatus.ACTIVE


@dataclass(kw_only=True)
class Customer(User):
    role: UserRole = field(default=UserRole.CUSTOMER, init=False)
    balance: Decimal = Decimal("0.00")
    default_address_id: str | None = None


@dataclass(kw_only=True)
class Merchant(User):
    role: UserRole = field(default=UserRole.MERCHANT, init=False)
    store_id: str | None = None
    timeout_count: int = 0
    accept_timeout_minutes: int = 10


@dataclass(kw_only=True)
class Rider(User):
    role: UserRole = field(default=UserRole.RIDER, init=False)
    employee_no: str = ""
    online: bool = False
    active_task_ids: list[str] = field(default_factory=list)
    completed_count: int = 0
    rating: float = 5.0


@dataclass(kw_only=True)
class Admin(User):
    role: UserRole = field(default=UserRole.ADMIN, init=False)
    admin_level: str = "平台管理员"


@dataclass(kw_only=True)
class Address:
    address_id: str
    customer_id: str
    receiver: str
    phone: str
    detail: str
    x_km: float
    y_km: float
    is_default: bool = False

    def full_text(self) -> str:
        return f"{self.detail}（{self.receiver} {self.phone}）"


# --------------------------------------------------------------------------- #
# 商家与菜单
# --------------------------------------------------------------------------- #
@dataclass(kw_only=True)
class Store:
    store_id: str
    merchant_id: str
    name: str
    description: str
    address_text: str
    x_km: float
    y_km: float
    status: StoreStatus = StoreStatus.OPEN
    notice: str = ""
    min_order_amount: Decimal = Decimal("0.00")
    rating: float = 5.0
    rating_count: int = 0
    accept_timeout_minutes: int = 10
    created_at: datetime = field(default_factory=_now)

    @property
    def is_open(self) -> bool:
        return self.status is StoreStatus.OPEN


@dataclass(kw_only=True)
class Category:
    category_id: str
    store_id: str
    name: str
    sort_no: int = 0


@dataclass(kw_only=True)
class Dish:
    dish_id: str
    store_id: str
    category_id: str
    name: str
    price: Decimal
    stock: int
    description: str = ""
    monthly_sales: int = 0
    status: DishStatus = DishStatus.ON_SALE
    created_at: datetime = field(default_factory=_now)

    @property
    def is_available(self) -> bool:
        return self.status is DishStatus.ON_SALE and self.stock > 0

    def take_stock(self, quantity: int) -> None:
        """扣减库存，售罄时自动迁移状态（REQ-004）。"""
        self.stock -= quantity
        if self.stock <= 0:
            self.stock = 0
            if self.status is DishStatus.ON_SALE:
                self.status = DishStatus.SOLD_OUT

    def restore_stock(self, quantity: int) -> None:
        self.stock += quantity
        if self.status is DishStatus.SOLD_OUT and self.stock > 0:
            self.status = DishStatus.ON_SALE


# --------------------------------------------------------------------------- #
# 购物车
# --------------------------------------------------------------------------- #
@dataclass(kw_only=True)
class CartItem:
    dish_id: str
    dish_name: str
    unit_price: Decimal
    quantity: int
    note: str = ""

    @property
    def subtotal(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass(kw_only=True)
class Cart:
    cart_id: str
    customer_id: str
    store_id: str | None = None
    items: dict[str, CartItem] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=_now)

    def add(self, item: CartItem) -> None:
        existing = self.items.get(item.dish_id)
        if existing:
            existing.quantity += item.quantity
        else:
            self.items[item.dish_id] = item
        self.updated_at = _now()

    def remove(self, dish_id: str) -> None:
        self.items.pop(dish_id, None)
        if not self.items:
            self.store_id = None
        self.updated_at = _now()

    @property
    def goods_amount(self) -> Decimal:
        return sum((item.subtotal for item in self.items.values()), Decimal("0.00"))

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items.values())


# --------------------------------------------------------------------------- #
# 订单与评价
# --------------------------------------------------------------------------- #
@dataclass(kw_only=True)
class OrderAddress:
    receiver: str
    phone: str
    detail: str
    x_km: float
    y_km: float

    def full_text(self) -> str:
        return f"{self.detail}（{self.receiver} {self.phone}）"


@dataclass(kw_only=True)
class OrderItem:
    dish_id: str
    dish_name: str
    unit_price: Decimal
    quantity: int

    @property
    def subtotal(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass(kw_only=True)
class StatusChange:
    status: OrderStatus
    changed_at: datetime = field(default_factory=_now)
    actor_id: str = "system"
    actor_role: str = "system"
    note: str = ""


@dataclass(kw_only=True)
class Order:
    order_id: str
    customer_id: str
    store_id: str
    store_name: str
    items: list[OrderItem]
    address: OrderAddress
    goods_amount: Decimal
    packing_fee: Decimal
    delivery_fee: Decimal
    discount_amount: Decimal
    payable_amount: Decimal
    status: OrderStatus = OrderStatus.PENDING_PAYMENT
    remark: str = ""
    fee_note: str = ""
    created_at: datetime = field(default_factory=_now)
    pay_deadline: datetime | None = None
    accept_deadline: datetime | None = None
    paid_at: datetime | None = None
    accepted_at: datetime | None = None
    ready_at: datetime | None = None
    delivered_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    refunded_at: datetime | None = None
    status_before_refund: OrderStatus | None = None
    delivery_task_id: str | None = None
    refund_id: str | None = None
    review_id: str | None = None
    cancel_reason: str = ""
    idempotency_key: str | None = None
    stock_released: bool = False
    status_history: list[StatusChange] = field(default_factory=list)

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)


@dataclass(kw_only=True)
class Review:
    review_id: str
    order_id: str
    store_id: str
    customer_id: str
    rating: int
    content: str = ""
    created_at: datetime = field(default_factory=_now)
    merchant_reply: str = ""


# --------------------------------------------------------------------------- #
# 支付、配送、退款
# --------------------------------------------------------------------------- #
@dataclass(kw_only=True)
class PaymentRecord:
    payment_id: str
    order_id: str
    amount: Decimal
    method: str = "模拟支付"
    status: PaymentStatus = PaymentStatus.PENDING
    transaction_no: str = ""
    created_at: datetime = field(default_factory=_now)
    paid_at: datetime | None = None
    refunded_at: datetime | None = None
    fail_reason: str = ""


@dataclass(kw_only=True)
class DeliveryTask:
    task_id: str
    order_id: str
    store_id: str
    pickup_text: str
    dropoff_text: str
    distance_km: float
    fee: Decimal
    status: DeliveryStatus = DeliveryStatus.PENDING
    rider_id: str | None = None
    created_at: datetime = field(default_factory=_now)
    deadline: datetime | None = None
    grabbed_at: datetime | None = None
    picked_at: datetime | None = None
    delivered_at: datetime | None = None
    dispatch_round: int = 1
    exception_reason: str = ""


@dataclass(kw_only=True)
class RefundRequest:
    refund_id: str
    order_id: str
    customer_id: str
    store_id: str
    amount: Decimal
    reason: str
    status_before_refund: OrderStatus
    status: RefundStatus = RefundStatus.PENDING
    responsible_party: ResponsibleParty = ResponsibleParty.UNDETERMINED
    created_at: datetime = field(default_factory=_now)
    deadline: datetime | None = None
    handled_at: datetime | None = None
    handler_id: str = ""
    handler_role: str = ""
    comment: str = ""
    arbitration_conclusion: str = ""


# --------------------------------------------------------------------------- #
# 消息与审计
# --------------------------------------------------------------------------- #
@dataclass(kw_only=True)
class Notification:
    notification_id: str
    user_id: str
    title: str
    body: str
    created_at: datetime = field(default_factory=_now)
    read: bool = False


@dataclass(kw_only=True)
class AuditLog:
    log_id: str
    actor_id: str
    actor_role: str
    action: str
    target_type: str
    target_id: str
    detail: str = ""
    result: str = "成功"
    created_at: datetime = field(default_factory=_now)
