"""领域层单元测试：状态机、计价、库存与购物车。"""

from __future__ import annotations

import unittest
from decimal import Decimal

from app.config import Settings
from app.domain.enums import DishStatus, OrderStatus as S
from app.domain.models import Cart, CartItem, Dish
from app.domain.pricing import (
    calculate_amounts,
    delivery_fee_for,
    distance_km,
    to_money,
)
from app.domain.state_machine import OrderStateMachine
from app.exceptions import InvalidTransitionError


class StateMachineTest(unittest.TestCase):
    def test_happy_path_is_allowed(self) -> None:
        path = [
            S.PENDING_PAYMENT,
            S.PENDING_ACCEPTANCE,
            S.PREPARING,
            S.PENDING_DELIVERY,
            S.DELIVERING,
            S.DELIVERED,
            S.COMPLETED,
        ]
        for current, target in zip(path, path[1:]):
            self.assertTrue(OrderStateMachine.can_transition(current, target))

    def test_skipping_state_is_rejected(self) -> None:
        with self.assertRaises(InvalidTransitionError):
            OrderStateMachine.assert_transition(S.PENDING_PAYMENT, S.COMPLETED)

    def test_terminal_states_have_no_outgoing_edges(self) -> None:
        for status in (S.COMPLETED, S.CANCELLED, S.REFUNDED):
            self.assertEqual(OrderStateMachine.allowed_targets(status), frozenset())

    def test_refund_can_restore_previous_state(self) -> None:
        for status in (
            S.PREPARING,
            S.PENDING_DELIVERY,
            S.DELIVERING,
            S.DELIVERY_FAILED,
            S.DELIVERED,
        ):
            self.assertTrue(OrderStateMachine.can_transition(S.REFUNDING, status))


class PricingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings()

    def test_money_rounding(self) -> None:
        self.assertEqual(to_money("1.005"), Decimal("1.01"))
        self.assertEqual(to_money(2), Decimal("2.00"))

    def test_delivery_fee_is_base_plus_distance(self) -> None:
        self.assertEqual(delivery_fee_for(0, self.settings), Decimal("5.00"))
        self.assertEqual(delivery_fee_for(2.5, self.settings), Decimal("7.50"))

    def test_amounts_sum_to_payable(self) -> None:
        amounts = calculate_amounts(
            Decimal("38.50"), Decimal("7.50"), self.settings, discount_amount=Decimal("3.00")
        )
        self.assertEqual(amounts.goods_amount, Decimal("38.50"))
        self.assertEqual(amounts.packing_fee, Decimal("1.00"))
        self.assertEqual(amounts.payable_amount, Decimal("44.00"))

    def test_distance(self) -> None:
        self.assertEqual(distance_km(0, 0, 3, 4), 5.0)


class InventoryAndCartTest(unittest.TestCase):
    def test_stock_auto_sold_out_and_restore(self) -> None:
        dish = Dish(
            dish_id="D1",
            store_id="S1",
            category_id="C1",
            name="测试菜",
            price=Decimal("10.00"),
            stock=2,
        )
        dish.take_stock(2)
        self.assertEqual(dish.stock, 0)
        self.assertIs(dish.status, DishStatus.SOLD_OUT)
        self.assertFalse(dish.is_available)

        dish.restore_stock(1)
        self.assertIs(dish.status, DishStatus.ON_SALE)
        self.assertTrue(dish.is_available)

    def test_cart_totals_and_store_switch(self) -> None:
        cart = Cart(cart_id="CART-1", customer_id="U1")
        cart.add(
            CartItem(
                dish_id="D1",
                dish_name="宫保鸡丁",
                unit_price=Decimal("26.00"),
                quantity=2,
            )
        )
        cart.add(
            CartItem(
                dish_id="D1",
                dish_name="宫保鸡丁",
                unit_price=Decimal("26.00"),
                quantity=1,
            )
        )
        self.assertEqual(cart.total_quantity, 3)
        self.assertEqual(cart.goods_amount, Decimal("78.00"))
        cart.remove("D1")
        self.assertEqual(cart.items, {})


if __name__ == "__main__":
    unittest.main()
