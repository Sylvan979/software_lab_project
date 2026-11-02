"""金额与计价规则（对应类图中的金额字段与 REQ-007、REQ-026）。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from app.config import Settings

CENT = Decimal("0.01")


def to_money(value: Decimal | int | float | str) -> Decimal:
    """统一金额精度，四舍五入到分。"""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def money_text(value: Decimal) -> str:
    return f"¥{to_money(value):.2f}"


@dataclass(frozen=True)
class AmountBreakdown:
    goods_amount: Decimal
    packing_fee: Decimal
    delivery_fee: Decimal
    discount_amount: Decimal
    payable_amount: Decimal

    @property
    def note(self) -> str:
        return ""


def delivery_fee_for(distance_km: float, settings: Settings) -> Decimal:
    """配送费 = 起步价 + 距离 × 单价（REQ-026 待确认的暂定规则）。"""
    if distance_km < 0:
        raise ValueError("配送距离不能为负")
    distance = Decimal(str(round(max(distance_km, 0.0), 2)))
    return to_money(settings.delivery_base_fee + distance * settings.delivery_per_km_fee)


def calculate_amounts(
    goods_amount: Decimal,
    delivery_fee: Decimal,
    settings: Settings,
    discount_amount: Decimal = Decimal("0.00"),
) -> AmountBreakdown:
    goods = to_money(goods_amount)
    packing = to_money(settings.packing_fee)
    delivery = to_money(delivery_fee)
    discount = to_money(discount_amount)
    payable = to_money(goods + packing + delivery - discount)
    if payable < 0:
        raise ValueError("优惠金额不能超过订单应付金额")
    return AmountBreakdown(
        goods_amount=goods,
        packing_fee=packing,
        delivery_fee=delivery,
        discount_amount=discount,
        payable_amount=payable,
    )


def distance_km(x1: float, y1: float, x2: float, y2: float) -> float:
    """按直线距离估算（REQ-024 不接入真实地图）。"""
    return round(((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5, 2)
