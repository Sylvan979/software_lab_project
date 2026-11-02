"""订单服务：创建、支付、接单、出餐、收货与超时兜底（REQ-007、REQ-009、REQ-013、REQ-018、REQ-019）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.enums import OrderStatus, UserRole
from app.domain.models import (
    Address,
    Order,
    OrderAddress,
    OrderItem,
    Review,
    StatusChange,
)
from app.domain.pricing import calculate_amounts, delivery_fee_for, distance_km
from app.exceptions import (
    ConflictError,
    OutOfRangeError,
    PermissionDeniedError,
    ValidationError,
)
from app.repository.repositories import Repositories
from app.services.audit import AuditService
from app.services.base import BaseService
from app.services.cart import CartService
from app.services.delivery import DeliveryService
from app.services.notifications import NotificationService
from app.services.order_lifecycle import OrderLifecycle
from app.services.payments import PaymentService

REJECT_REASONS = ("缺货", "太忙", "地址太远", "其他")


@dataclass(frozen=True)
class CheckoutResult:
    order: Order
    reused: bool = False


class OrderService(BaseService):
    def __init__(
        self,
        repos: Repositories,
        settings,
        audit: AuditService,
        notifications: NotificationService,
        lifecycle: OrderLifecycle,
        payments: PaymentService,
        cart: CartService,
        delivery: DeliveryService,
    ) -> None:
        super().__init__(repos, settings)
        self.audit = audit
        self.notifications = notifications
        self.lifecycle = lifecycle
        self.payments = payments
        self.cart = cart
        self.delivery = delivery

    # ------------------------------------------------------------------ #
    # 下单
    # ------------------------------------------------------------------ #
    def checkout(
        self,
        customer_id: str,
        address_id: str,
        *,
        remark: str = "",
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> CheckoutResult:
        now = now or datetime.now()
        self.require_customer(customer_id)
        if idempotency_key:
            existing = self.repos.orders.find_by_idempotency(customer_id, idempotency_key)
            if existing is not None:
                return CheckoutResult(order=existing, reused=True)

        summary = self.cart.validate_for_checkout(customer_id)
        store = summary.store
        assert store is not None
        address = self._own_address(customer_id, address_id)
        distance = distance_km(store.x_km, store.y_km, address.x_km, address.y_km)
        if distance > self.settings.delivery_radius_km:
            raise OutOfRangeError(
                f"收货地址距店铺 {distance:.2f} km，超出 "
                f"{self.settings.delivery_radius_km:.0f} km 配送范围"
            )
        if len(remark) > 100:
            raise ValidationError("订单备注不能超过 100 个字符")

        items: list[OrderItem] = []
        for line in summary.lines:
            dish = line.dish
            assert dish is not None
            if not dish.is_available or dish.stock < line.item.quantity:
                raise ConflictError(f"「{dish.name}」库存不足，请刷新购物车")
            items.append(
                OrderItem(
                    dish_id=dish.dish_id,
                    dish_name=dish.name,
                    unit_price=dish.price,  # 下单价格快照（REQ-007）
                    quantity=line.item.quantity,
                )
            )
        amounts = calculate_amounts(
            summary.goods_amount,
            delivery_fee_for(distance, self.settings),
            self.settings,
        )

        with self.repos.transaction():
            for item in items:
                dish = self.repos.dishes.get(item.dish_id)
                dish.take_stock(item.quantity)
                self.repos.dishes.update(dish)
            order = Order(
                order_id=self.repos.db.next_id("ORD"),
                customer_id=customer_id,
                store_id=store.store_id,
                store_name=store.name,
                items=items,
                address=OrderAddress(
                    receiver=address.receiver,
                    phone=address.phone,
                    detail=address.detail,
                    x_km=address.x_km,
                    y_km=address.y_km,
                ),
                goods_amount=amounts.goods_amount,
                packing_fee=amounts.packing_fee,
                delivery_fee=amounts.delivery_fee,
                discount_amount=amounts.discount_amount,
                payable_amount=amounts.payable_amount,
                remark=remark.strip(),
                fee_note="配送费按暂定规则：起步 5 元 + 1 元/公里（REQ-026 待确认）",
                pay_deadline=now + timedelta(minutes=self.settings.payment_timeout_minutes),
                idempotency_key=idempotency_key,
                status_history=[
                    StatusChange(
                        status=OrderStatus.PENDING_PAYMENT,
                        changed_at=now,
                        actor_id=customer_id,
                        actor_role=UserRole.CUSTOMER.label,
                        note="提交订单",
                    )
                ],
            )
            self.repos.orders.add(order)
            self.cart.clear(customer_id)
            self.audit.record(
                actor_id=customer_id,
                actor_role=UserRole.CUSTOMER.label,
                action="提交订单",
                target_type="订单",
                target_id=order.order_id,
                detail=f"{store.name}，应付 ¥{order.payable_amount:.2f}",
            )
        return CheckoutResult(order=order)

    # ------------------------------------------------------------------ #
    # 支付与取消
    # ------------------------------------------------------------------ #
    def pay(
        self,
        order_id: str,
        customer_id: str,
        *,
        success: bool = True,
        now: datetime | None = None,
    ) -> Order:
        now = now or datetime.now()
        with self._lock:
            order = self._own_order(order_id, customer_id)
            if order.status is not OrderStatus.PENDING_PAYMENT:
                raise ConflictError(f"订单当前为「{order.status.label}」，不能支付")
            if order.pay_deadline and now > order.pay_deadline:
                self._cancel_unpaid(order, now, reason="支付超时")
                raise ConflictError("订单已超过 15 分钟支付时限，已自动取消")

            self.payments.charge(order, success=success, now=now)
            if not success:
                self._cancel_unpaid(order, now, reason="支付失败")
                return self.repos.orders.get(order_id)

            store = self.repos.stores.get(order.store_id)
            order.paid_at = now
            order.accept_deadline = now + timedelta(minutes=store.accept_timeout_minutes)
            self.lifecycle.transition(
                order,
                OrderStatus.PENDING_ACCEPTANCE,
                actor_id=customer_id,
                actor_role=UserRole.CUSTOMER,
                note=f"模拟支付成功 ¥{order.payable_amount:.2f}",
                now=now,
            )
            self.notifications.send(
                store.merchant_id,
                "新订单待接单",
                f"{order.store_name}：订单 {order.order_id}，请在 "
                f"{store.accept_timeout_minutes} 分钟内处理",
            )
            self.notifications.send(
                customer_id, "支付成功", f"订单 {order.order_id} 已通知商家接单"
            )
            return self.repos.orders.get(order_id)

    def cancel(self, order_id: str, customer_id: str, reason: str = "顾客主动取消") -> Order:
        with self._lock:
            order = self._own_order(order_id, customer_id)
            if order.status is OrderStatus.PENDING_PAYMENT:
                return self._cancel_unpaid(order, datetime.now(), reason=reason)
            if order.status is OrderStatus.PENDING_ACCEPTANCE:
                self.payments.refund(order)
                self.lifecycle.release_stock(order)
                self.lifecycle.transition(
                    order,
                    OrderStatus.CANCELLED,
                    actor_id=customer_id,
                    actor_role=UserRole.CUSTOMER,
                    note=reason,
                )
                self.notifications.send(
                    self.repos.stores.get(order.store_id).merchant_id,
                    "订单已取消",
                    f"订单 {order.order_id} 被顾客取消，已原路退款",
                )
                return order
            raise ConflictError(
                f"订单已进入「{order.status.label}」，请在订单详情中申请退款"
            )

    def _cancel_unpaid(self, order: Order, now: datetime, *, reason: str) -> Order:
        self.lifecycle.release_stock(order)
        order.cancel_reason = reason
        self.lifecycle.transition(
            order,
            OrderStatus.CANCELLED,
            actor_id="system",
            actor_role="系统",
            note=reason,
            now=now,
        )
        self.notifications.send(order.customer_id, "订单已取消", reason)
        return order

    # ------------------------------------------------------------------ #
    # 商家操作
    # ------------------------------------------------------------------ #
    def merchant_accept(
        self, order_id: str, merchant_id: str, *, now: datetime | None = None
    ) -> Order:
        now = now or datetime.now()
        order = self._merchant_order(order_id, merchant_id)
        if order.status is OrderStatus.PREPARING:
            return order  # 重复接单返回当前状态（REQ-009）
        if order.status is not OrderStatus.PENDING_ACCEPTANCE:
            raise ConflictError(f"订单当前为「{order.status.label}」，不能接单")
        if order.accept_deadline and now > order.accept_deadline:
            self.handle_accept_timeout(order_id, now)
            raise ConflictError("订单已超过接单时限，系统已自动取消并退款")
        self.lifecycle.transition(
            order,
            OrderStatus.PREPARING,
            actor_id=merchant_id,
            actor_role=UserRole.MERCHANT,
            note="商家接单",
            now=now,
        )
        self.notifications.send(
            order.customer_id, "商家已接单", f"「{order.store_name}」正在为您制作"
        )
        return order

    def merchant_reject(
        self, order_id: str, merchant_id: str, reason: str, *, now: datetime | None = None
    ) -> Order:
        now = now or datetime.now()
        order = self._merchant_order(order_id, merchant_id)
        if reason not in REJECT_REASONS:
            raise ValidationError("请选择拒单原因（缺货 / 太忙 / 地址太远 / 其他）")
        if order.status is OrderStatus.CANCELLED:
            return order
        if order.status is not OrderStatus.PENDING_ACCEPTANCE:
            raise ConflictError(f"订单当前为「{order.status.label}」，不能拒单")
        self.payments.refund(order, now=now)
        self.lifecycle.release_stock(order)
        order.cancel_reason = f"商家拒单：{reason}"
        self.lifecycle.transition(
            order,
            OrderStatus.CANCELLED,
            actor_id=merchant_id,
            actor_role=UserRole.MERCHANT,
            note=order.cancel_reason,
            now=now,
        )
        self.notifications.send(
            order.customer_id,
            "商家已拒单",
            f"原因：{reason}，订单已全额退款",
        )
        return order

    def mark_ready(self, order_id: str, merchant_id: str, *, now: datetime | None = None) -> Order:
        now = now or datetime.now()
        order = self._merchant_order(order_id, merchant_id)
        if order.status is OrderStatus.PENDING_DELIVERY:
            return order
        if order.status is not OrderStatus.PREPARING:
            raise ConflictError(f"订单当前为「{order.status.label}」，不能标记出餐")
        self.lifecycle.transition(
            order,
            OrderStatus.PENDING_DELIVERY,
            actor_id=merchant_id,
            actor_role=UserRole.MERCHANT,
            note="商家出餐",
            now=now,
        )
        self.delivery.create_task(order, now=now)
        self.notifications.send(
            order.customer_id, "餐品已出餐", "配送员正在赶往店铺取餐"
        )
        return self.repos.orders.get(order_id)

    # ------------------------------------------------------------------ #
    # 顾客收货与评价
    # ------------------------------------------------------------------ #
    def confirm_receipt(
        self, order_id: str, customer_id: str, *, now: datetime | None = None
    ) -> Order:
        order = self._own_order(order_id, customer_id)
        if order.status is OrderStatus.COMPLETED:
            return order
        if order.status is not OrderStatus.DELIVERED:
            raise ConflictError(f"订单当前为「{order.status.label}」，不能确认收货")
        self.lifecycle.transition(
            order,
            OrderStatus.COMPLETED,
            actor_id=customer_id,
            actor_role=UserRole.CUSTOMER,
            note="顾客确认收货",
            now=now,
        )
        self.notifications.send(
            self.repos.stores.get(order.store_id).merchant_id,
            "订单已完成",
            f"订单 {order.order_id} 顾客已确认收货",
        )
        return order

    def review(
        self,
        order_id: str,
        customer_id: str,
        rating: int,
        content: str = "",
    ) -> Order:
        order = self._own_order(order_id, customer_id)
        if order.status is not OrderStatus.COMPLETED:
            raise ConflictError("订单完成后才能评价")
        if order.review_id:
            raise ConflictError("该订单已评价")
        if not 1 <= int(rating) <= 5:
            raise ValidationError("评分需在 1~5 之间")
        if len(content) > 200:
            raise ValidationError("评价内容不能超过 200 个字符")
        review = Review(
            review_id=self.repos.db.next_id("REV"),
            order_id=order_id,
            store_id=order.store_id,
            customer_id=customer_id,
            rating=int(rating),
            content=content.strip(),
        )
        self.repos.reviews.add(review)
        order.review_id = review.review_id
        self.repos.orders.update(order)

        store = self.repos.stores.get(order.store_id)
        total = store.rating * store.rating_count + review.rating
        store.rating_count += 1
        store.rating = round(total / store.rating_count, 2)
        self.repos.stores.update(store)
        self.notifications.send(
            store.merchant_id,
            "收到新的评价",
            f"{review.rating} 星：{review.content or '（无文字评价）'}",
        )
        return order

    # ------------------------------------------------------------------ #
    # 定时任务入口
    # ------------------------------------------------------------------ #
    def handle_payment_timeout(self, order_id: str, now: datetime | None = None) -> Order | None:
        now = now or datetime.now()
        order = self.repos.orders.find(order_id)
        if order is None or order.status is not OrderStatus.PENDING_PAYMENT:
            return None
        if order.pay_deadline and now < order.pay_deadline:
            return None
        return self._cancel_unpaid(order, now, reason="超过 15 分钟未支付，订单自动取消")

    def handle_accept_timeout(self, order_id: str, now: datetime | None = None) -> Order | None:
        now = now or datetime.now()
        order = self.repos.orders.find(order_id)
        if order is None or order.status is not OrderStatus.PENDING_ACCEPTANCE:
            return None
        if order.accept_deadline and now < order.accept_deadline:
            return None
        store = self.repos.stores.get(order.store_id)
        merchant = self.get_user(store.merchant_id)
        if hasattr(merchant, "timeout_count"):
            merchant.timeout_count += 1
            self.repos.users.update(merchant)
        try:
            self.payments.refund(order, now=now)
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            pass
        self.lifecycle.release_stock(order)
        order.cancel_reason = "超时未接单，系统自动取消"
        self.lifecycle.transition(
            order,
            OrderStatus.CANCELLED,
            actor_id="system",
            actor_role="系统",
            note=order.cancel_reason,
            now=now,
        )
        self.notifications.send(
            order.customer_id, "订单已自动取消", "商家超时未接单，已全额退款"
        )
        self.notifications.send(
            store.merchant_id, "订单超时未接单", f"订单 {order.order_id} 已自动取消"
        )
        return order

    def handle_auto_complete(self, order_id: str, now: datetime | None = None) -> Order | None:
        now = now or datetime.now()
        order = self.repos.orders.find(order_id)
        if order is None or order.status is not OrderStatus.DELIVERED:
            return None
        if order.delivered_at is None:
            return None
        if now < order.delivered_at + timedelta(hours=self.settings.auto_complete_hours):
            return None
        self.lifecycle.transition(
            order,
            OrderStatus.COMPLETED,
            actor_id="system",
            actor_role="系统",
            note="送达 24 小时后自动确认收货",
            now=now,
        )
        self.notifications.send(order.customer_id, "订单已自动完成", "感谢您的使用")
        return order

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def get_visible_order(self, order_id: str, user_id: str) -> Order:
        user = self.require_user(user_id)
        order = self.repos.orders.get(order_id)
        if user.role is UserRole.CUSTOMER and order.customer_id != user_id:
            raise PermissionDeniedError("不能查看他人的订单")
        if user.role is UserRole.MERCHANT:
            store = self.repos.stores.by_merchant(user_id)
            if store is None or order.store_id != store.store_id:
                raise PermissionDeniedError("不能查看其他店铺的订单")
        if user.role is UserRole.RIDER:
            task = self.repos.deliveries.by_order(order_id)
            if task is None or task.rider_id != user_id:
                raise PermissionDeniedError("不能查看未分配给自己的订单")
        return order

    def list_for_customer(self, customer_id: str) -> list[Order]:
        self.require_customer(customer_id)
        return self.repos.orders.by_customer(customer_id)

    def list_for_store(self, merchant_id: str) -> list[Order]:
        self.require_merchant(merchant_id)
        store = self.repos.stores.by_merchant(merchant_id)
        if store is None:
            return []
        return self.repos.orders.by_store(store.store_id)

    def list_pending_acceptance(self, merchant_id: str) -> list[Order]:
        return [
            o
            for o in self.list_for_store(merchant_id)
            if o.status is OrderStatus.PENDING_ACCEPTANCE
        ]

    def _own_order(self, order_id: str, customer_id: str) -> Order:
        self.require_customer(customer_id)
        order = self.repos.orders.get(order_id)
        if order.customer_id != customer_id:
            raise PermissionDeniedError("不能操作他人的订单")
        return order

    def _merchant_order(self, order_id: str, merchant_id: str) -> Order:
        self.require_merchant(merchant_id)
        order = self.repos.orders.get(order_id)
        store = self.repos.stores.by_merchant(merchant_id)
        if store is None or order.store_id != store.store_id:
            raise PermissionDeniedError("不能操作其他店铺的订单")
        return order

    def _own_address(self, customer_id: str, address_id: str) -> Address:
        address = self.repos.addresses.get(address_id)
        if address.customer_id != customer_id:
            raise PermissionDeniedError("不能使用他人的收货地址")
        if not address.receiver or not address.phone or not address.detail:
            raise ValidationError("收货地址不完整，请补充门牌信息")
        return address
