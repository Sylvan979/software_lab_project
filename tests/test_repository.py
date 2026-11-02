"""持久化层测试：编解码往返、原子落盘与主键生成。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.domain.enums import OrderStatus, UserRole
from app.domain.models import (
    Address,
    Cart,
    CartItem,
    Customer,
    Merchant,
    Order,
    OrderAddress,
    OrderItem,
    StatusChange,
)
from app.repository.database import JsonDatabase
from app.repository.repositories import Repositories


class RepositoryRoundTripTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "platform.json"
        self.db = JsonDatabase(self.path)
        self.repos = Repositories(self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_user_subtype_survives_reload(self) -> None:
        customer = Customer(
            user_id=self.db.next_id("USR"),
            phone="13800000001",
            nickname="陈晓",
            balance=Decimal("12.50"),
        )
        merchant = Merchant(
            user_id=self.db.next_id("USR"),
            phone="13900000001",
            nickname="老张",
            timeout_count=2,
        )
        self.repos.users.add(customer)
        self.repos.users.add(merchant)
        self.db.save()

        reloaded = Repositories(JsonDatabase(self.path)).users
        first = reloaded.get(customer.user_id)
        second = reloaded.get(merchant.user_id)
        self.assertIsInstance(first, Customer)
        self.assertIsInstance(second, Merchant)
        self.assertEqual(first.role, UserRole.CUSTOMER)
        self.assertEqual(first.balance, Decimal("12.50"))
        self.assertEqual(second.timeout_count, 2)

    def test_nested_order_and_cart_round_trip(self) -> None:
        order = Order(
            order_id="ORD-0001",
            customer_id="USR-0001",
            store_id="STR-0001",
            store_name="川味小厨",
            items=[
                OrderItem(
                    dish_id="DSH-0001",
                    dish_name="宫保鸡丁",
                    unit_price=Decimal("26.00"),
                    quantity=2,
                )
            ],
            address=OrderAddress(receiver="陈晓", phone="138****0001", detail="A 栋 302", x_km=1.0, y_km=1.0),
            goods_amount=Decimal("52.00"),
            packing_fee=Decimal("1.00"),
            delivery_fee=Decimal("6.00"),
            discount_amount=Decimal("0.00"),
            payable_amount=Decimal("59.00"),
            pay_deadline=datetime(2026, 11, 2, 12, 0, 0),
            status_history=[StatusChange(status=OrderStatus.PENDING_PAYMENT)],
        )
        self.repos.orders.add(order)
        cart = Cart(
            cart_id="CRT-0001",
            customer_id="USR-0001",
            store_id="STR-0001",
            items={
                "DSH-0001": CartItem(
                    dish_id="DSH-0001",
                    dish_name="宫保鸡丁",
                    unit_price=Decimal("26.00"),
                    quantity=2,
                )
            },
        )
        self.repos.carts.add(cart)
        self.db.save()

        repos = Repositories(JsonDatabase(self.path))
        loaded = repos.orders.get("ORD-0001")
        self.assertEqual(loaded.status, OrderStatus.PENDING_PAYMENT)
        self.assertEqual(loaded.items[0].unit_price, Decimal("26.00"))
        self.assertEqual(loaded.address.detail, "A 栋 302")
        self.assertEqual(loaded.pay_deadline, datetime(2026, 11, 2, 12, 0, 0))
        loaded_cart = repos.carts.by_customer("USR-0001")
        assert loaded_cart is not None
        self.assertEqual(loaded_cart.items["DSH-0001"].quantity, 2)

    def test_ids_are_not_reused_after_reload(self) -> None:
        first = self.db.next_id("ORD")
        self.db.save()
        second_db = JsonDatabase(self.path)
        second = second_db.next_id("ORD")
        self.assertEqual((first, second), ("ORD-0001", "ORD-0002"))

    def test_address_round_trip(self) -> None:
        address = Address(
            address_id="ADR-0001",
            customer_id="USR-0001",
            receiver="陈晓",
            phone="13800000001",
            detail="A 栋 302",
            x_km=0.5,
            y_km=1.2,
        )
        self.repos.addresses.add(address)
        self.db.save()
        loaded = Repositories(JsonDatabase(self.path)).addresses.get("ADR-0001")
        self.assertEqual(loaded.x_km, 0.5)
        self.assertFalse(loaded.is_default)


if __name__ == "__main__":
    unittest.main()
