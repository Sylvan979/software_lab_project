"""领域枚举。

枚举成员使用稳定的英文编码值持久化，中文名称只用于界面展示；
这样后续改文案不会破坏历史数据。
"""

from __future__ import annotations

from enum import Enum


class LabeledEnum(str, Enum):
    """带中文标签的字符串枚举。"""

    @property
    def label(self) -> str:
        return _LABELS.get(self, self.value)


class UserRole(LabeledEnum):
    CUSTOMER = "customer"
    MERCHANT = "merchant"
    RIDER = "rider"
    ADMIN = "admin"


class AccountStatus(LabeledEnum):
    ACTIVE = "active"
    FROZEN = "frozen"


class StoreStatus(LabeledEnum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    SUSPENDED = "suspended"
    REJECTED = "rejected"


class DishStatus(LabeledEnum):
    ON_SALE = "on_sale"
    SOLD_OUT = "sold_out"
    OFF_SHELF = "off_shelf"


class OrderStatus(LabeledEnum):
    PENDING_PAYMENT = "pending_payment"
    PENDING_ACCEPTANCE = "pending_acceptance"
    PREPARING = "preparing"
    PENDING_DELIVERY = "pending_delivery"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDING = "refunding"
    REFUNDED = "refunded"
    DELIVERY_FAILED = "delivery_failed"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_ORDER_STATUSES

    @property
    def is_active(self) -> bool:
        return not self.is_terminal


class PaymentStatus(LabeledEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class DeliveryStatus(LabeledEnum):
    PENDING = "pending"
    GRABBED = "grabbed"
    PICKED = "picked"
    DELIVERED = "delivered"
    FAILED = "failed"
    MANUAL = "manual"


class RefundStatus(LabeledEnum):
    PENDING = "pending"
    APPROVED = "approved"
    AUTO_APPROVED = "auto_approved"
    REJECTED = "rejected"
    ARBITRATED = "arbitrated"


class ResponsibleParty(LabeledEnum):
    CUSTOMER = "customer"
    MERCHANT = "merchant"
    RIDER = "rider"
    PLATFORM = "platform"
    UNDETERMINED = "undetermined"


TERMINAL_ORDER_STATUSES = frozenset(
    {OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.REFUNDED}
)

_LABELS: dict[Enum, str] = {
    UserRole.CUSTOMER: "顾客",
    UserRole.MERCHANT: "商家",
    UserRole.RIDER: "配送员",
    UserRole.ADMIN: "平台管理员",
    AccountStatus.ACTIVE: "正常",
    AccountStatus.FROZEN: "已冻结",
    StoreStatus.PENDING: "待审核",
    StoreStatus.OPEN: "营业中",
    StoreStatus.CLOSED: "休息中",
    StoreStatus.SUSPENDED: "已关停",
    StoreStatus.REJECTED: "审核未通过",
    DishStatus.ON_SALE: "已上架",
    DishStatus.SOLD_OUT: "已售罄",
    DishStatus.OFF_SHELF: "已下架",
    OrderStatus.PENDING_PAYMENT: "待支付",
    OrderStatus.PENDING_ACCEPTANCE: "待接单",
    OrderStatus.PREPARING: "制作中",
    OrderStatus.PENDING_DELIVERY: "待配送",
    OrderStatus.DELIVERING: "配送中",
    OrderStatus.DELIVERED: "已送达",
    OrderStatus.COMPLETED: "已完成",
    OrderStatus.CANCELLED: "已取消",
    OrderStatus.REFUNDING: "退款中",
    OrderStatus.REFUNDED: "已退款",
    OrderStatus.DELIVERY_FAILED: "配送失败",
    PaymentStatus.PENDING: "待支付",
    PaymentStatus.PAID: "已支付",
    PaymentStatus.FAILED: "支付失败",
    PaymentStatus.REFUNDED: "已退款",
    DeliveryStatus.PENDING: "待抢单",
    DeliveryStatus.GRABBED: "已接单",
    DeliveryStatus.PICKED: "已取餐",
    DeliveryStatus.DELIVERED: "已送达",
    DeliveryStatus.FAILED: "配送失败",
    DeliveryStatus.MANUAL: "待人工调度",
    RefundStatus.PENDING: "待处理",
    RefundStatus.APPROVED: "已同意",
    RefundStatus.AUTO_APPROVED: "超时自动同意",
    RefundStatus.REJECTED: "已驳回",
    RefundStatus.ARBITRATED: "平台已仲裁",
    ResponsibleParty.CUSTOMER: "顾客",
    ResponsibleParty.MERCHANT: "商家",
    ResponsibleParty.RIDER: "配送员",
    ResponsibleParty.PLATFORM: "平台",
    ResponsibleParty.UNDETERMINED: "待判定",
}
