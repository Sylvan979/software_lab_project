"""购物车服务（REQ-006）。

一个购物车只能来自同一家店铺；数量变化时实时校验库存。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.models import Cart, CartItem, Dish, Store
from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.repository.repositories import Repositories
from app.services.base import BaseService


@dataclass(frozen=True)
class CartLine:
    item: CartItem
    dish: Dish | None

    @property
    def available(self) -> bool:
        return (
            self.dish is not None
            and self.dish.is_available
            and self.dish.stock >= self.item.quantity
        )


@dataclass(frozen=True)
class CartSummary:
    cart: Cart
    store: Store | None
    lines: list[CartLine]
    goods_amount: Decimal
    issues: list[str]

    @property
    def total_quantity(self) -> int:
        return self.cart.total_quantity

    @property
    def can_checkout(self) -> bool:
        return bool(self.lines) and not self.issues


class CartService(BaseService):
    def __init__(self, repos: Repositories, settings) -> None:
        super().__init__(repos, settings)

    def get_cart(self, customer_id: str) -> Cart:
        self.require_customer(customer_id)
        cart = self.repos.carts.by_customer(customer_id)
        if cart is None:
            cart = Cart(
                cart_id=self.repos.db.next_id("CRT"),
                customer_id=customer_id,
            )
            self.repos.carts.add(cart)
        return cart

    def add_item(
        self, customer_id: str, dish_id: str, quantity: int = 1, note: str = ""
    ) -> Cart:
        if quantity < 1 or quantity > 99:
            raise ValidationError("数量需在 1~99 之间")
        dish = self.repos.dishes.get(dish_id)
        store = self.repos.stores.get(dish.store_id)
        if not store.is_open:
            raise ConflictError("店铺休息中，暂不能下单")
        if not dish.is_available:
            raise ConflictError(f"「{dish.name}」已售罄或已下架")

        cart = self.get_cart(customer_id)
        if cart.store_id and cart.store_id != store.store_id:
            current = self.repos.stores.find(cart.store_id)
            raise ConflictError(
                f"购物车中已有「{current.name if current else '其他店铺'}」的菜品，"
                "一个购物车只能来自同一家店铺，请先清空购物车"
            )
        existing = cart.items.get(dish_id)
        new_quantity = quantity + (existing.quantity if existing else 0)
        if new_quantity > dish.stock:
            raise ConflictError(f"「{dish.name}」库存仅剩 {dish.stock} 份")

        cart.add(
            CartItem(
                dish_id=dish.dish_id,
                dish_name=dish.name,
                unit_price=dish.price,
                quantity=quantity,
                note=note.strip(),
            )
        )
        cart.store_id = store.store_id
        self.repos.carts.update(cart)
        return cart

    def update_quantity(self, customer_id: str, dish_id: str, quantity: int) -> Cart:
        cart = self.get_cart(customer_id)
        if dish_id not in cart.items:
            raise NotFoundError("购物车中不存在该菜品")
        if quantity <= 0:
            cart.remove(dish_id)
            self.repos.carts.update(cart)
            return cart
        if quantity > 99:
            raise ValidationError("单个菜品最多购买 99 份")
        dish = self.repos.dishes.find(dish_id)
        if dish and quantity > dish.stock:
            raise ConflictError(f"「{dish.name}」库存仅剩 {dish.stock} 份")
        cart.items[dish_id].quantity = quantity
        self.repos.carts.update(cart)
        return cart

    def remove_item(self, customer_id: str, dish_id: str) -> Cart:
        cart = self.get_cart(customer_id)
        cart.remove(dish_id)
        self.repos.carts.update(cart)
        return cart

    def clear(self, customer_id: str) -> Cart:
        cart = self.get_cart(customer_id)
        cart.items.clear()
        cart.store_id = None
        self.repos.carts.update(cart)
        return cart

    def summary(self, customer_id: str) -> CartSummary:
        cart = self.get_cart(customer_id)
        store = self.repos.stores.find(cart.store_id)
        issues: list[str] = []
        lines: list[CartLine] = []
        for item in cart.items.values():
            dish = self.repos.dishes.find(item.dish_id)
            line = CartLine(item=item, dish=dish)
            lines.append(line)
            if dish is None:
                issues.append(f"「{item.dish_name}」已不存在，请移除")
            elif not dish.is_available:
                issues.append(f"「{dish.name}」已售罄，请移除")
            elif dish.stock < item.quantity:
                issues.append(f"「{dish.name}」库存仅剩 {dish.stock} 份")
        if store is None:
            issues.append("购物车为空")
        elif not store.is_open:
            issues.append(f"「{store.name}」当前休息中，暂不能下单")
        return CartSummary(
            cart=cart,
            store=store,
            lines=lines,
            goods_amount=cart.goods_amount,
            issues=issues,
        )

    def validate_for_checkout(self, customer_id: str) -> CartSummary:
        summary = self.summary(customer_id)
        if not summary.lines:
            raise ConflictError("购物车为空，请先选择菜品")
        if summary.issues:
            raise ConflictError("；".join(summary.issues))
        if summary.store and summary.goods_amount < summary.store.min_order_amount:
            raise ConflictError(
                f"未达到「{summary.store.name}」起送价 ¥{summary.store.min_order_amount:.2f}"
            )
        return summary
