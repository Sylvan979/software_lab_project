"""订单状态机（对应实验二状态图，图 6）。

状态机只回答"能不能迁移"，不关心是谁在操作；角色鉴权由服务层完成。
集中维护迁移表的好处是：新增状态时只需改这一处，非法迁移在服务层统一被拒。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import OrderStatus as S
from app.exceptions import InvalidTransitionError


@dataclass(frozen=True)
class Transition:
    source: S
    target: S
    action: str
    note: str = ""


TRANSITIONS: tuple[Transition, ...] = (
    Transition(S.PENDING_PAYMENT, S.PENDING_ACCEPTANCE, "支付成功"),
    Transition(S.PENDING_PAYMENT, S.CANCELLED, "取消订单或支付超时"),
    Transition(S.PENDING_ACCEPTANCE, S.PREPARING, "商家接单"),
    Transition(S.PENDING_ACCEPTANCE, S.CANCELLED, "商家拒单、接单超时或顾客取消"),
    Transition(S.PREPARING, S.PENDING_DELIVERY, "商家出餐"),
    Transition(S.PREPARING, S.REFUNDING, "申请退款"),
    Transition(S.PENDING_DELIVERY, S.DELIVERING, "骑手取餐"),
    Transition(S.PENDING_DELIVERY, S.REFUNDING, "无人接单或顾客申请退款"),
    Transition(S.DELIVERING, S.DELIVERED, "骑手确认送达"),
    Transition(S.DELIVERING, S.REFUNDING, "顾客申请退款"),
    Transition(S.DELIVERING, S.DELIVERY_FAILED, "骑手上报配送异常"),
    Transition(S.DELIVERY_FAILED, S.DELIVERING, "平台重新派单"),
    Transition(S.DELIVERY_FAILED, S.REFUNDING, "判定无法送达"),
    Transition(S.DELIVERED, S.COMPLETED, "确认收货或超时自动确认"),
    Transition(S.DELIVERED, S.REFUNDING, "售后期内申请退款"),
    Transition(S.REFUNDING, S.REFUNDED, "退款通过"),
    Transition(S.REFUNDING, S.COMPLETED, "退款驳回且订单已送达"),
    Transition(S.REFUNDING, S.CANCELLED, "退款驳回且订单未出餐"),
    # 退款被驳回且订单仍在履约中：恢复申请前的状态（REQ-012）
    Transition(S.REFUNDING, S.PREPARING, "退款驳回，恢复制作中"),
    Transition(S.REFUNDING, S.PENDING_DELIVERY, "退款驳回，恢复待配送"),
    Transition(S.REFUNDING, S.DELIVERING, "退款驳回，恢复配送中"),
    Transition(S.REFUNDING, S.DELIVERY_FAILED, "退款驳回，恢复配送失败"),
    Transition(S.REFUNDING, S.DELIVERED, "退款驳回，恢复已送达"),
)

_ALLOWED: dict[tuple[S, S], Transition] = {(t.source, t.target): t for t in TRANSITIONS}

TERMINAL: frozenset[S] = frozenset({S.COMPLETED, S.CANCELLED, S.REFUNDED})


class OrderStateMachine:
    """无状态的状态机工具类。"""

    @staticmethod
    def can_transition(current: S, target: S) -> bool:
        return (current, target) in _ALLOWED

    @staticmethod
    def assert_transition(current: S, target: S) -> Transition:
        transition = _ALLOWED.get((current, target))
        if transition is None:
            raise InvalidTransitionError(current.label, target.label)
        return transition

    @staticmethod
    def allowed_targets(current: S) -> frozenset[S]:
        return frozenset(target for source, target in _ALLOWED if source is current)

    @staticmethod
    def action_of(current: S, target: S) -> str:
        return OrderStateMachine.assert_transition(current, target).action

    @staticmethod
    def is_terminal(status: S) -> bool:
        return status in TERMINAL
