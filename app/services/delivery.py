"""配送服务：派单、抢单、取餐、送达与异常（REQ-010、REQ-011、REQ-021）。

配送任务与订单分离：一笔订单可能经历多个配送任务（异常后重派）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.enums import DeliveryStatus, OrderStatus, UserRole
from app.domain.models import DeliveryTask, Order, Rider
from app.domain.pricing import distance_km
from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.repository.repositories import Repositories
from app.services.audit import AuditService
from app.services.base import BaseService
from app.services.notifications import NotificationService
from app.services.order_lifecycle import OrderLifecycle
from app.services.privacy import mask_detail, mask_phone

EXCEPTION_REASONS = ("联系不上顾客", "地址错误", "交通事故", "车辆故障", "其他")


class DeliveryService(BaseService):
    def __init__(
        self,
        repos: Repositories,
        settings,
        audit: AuditService,
        notifications: NotificationService,
        lifecycle: OrderLifecycle,
    ) -> None:
        super().__init__(repos, settings)
        self.audit = audit
        self.notifications = notifications
        self.lifecycle = lifecycle

    # ------------------------------------------------------------------ #
    # 任务创建
    # ------------------------------------------------------------------ #
    def create_task(self, order: Order, *, now: datetime | None = None) -> DeliveryTask:
        now = now or datetime.now()
        store = self.repos.stores.get(order.store_id)
        distance = distance_km(
            store.x_km, store.y_km, order.address.x_km, order.address.y_km
        )
        task = DeliveryTask(
            task_id=self.repos.db.next_id("DLV"),
            order_id=order.order_id,
            store_id=order.store_id,
            pickup_text=store.address_text,
            dropoff_text=order.address.detail,
            distance_km=distance,
            fee=order.delivery_fee,
            deadline=now + timedelta(minutes=self.settings.dispatch_timeout_minutes),
        )
        self.repos.deliveries.add(task)
        order.delivery_task_id = task.task_id
        self.repos.orders.update(order)

        for rider in self.repos.users.riders():
            if rider.online:
                self.notifications.send(
                    rider.user_id,
                    "新的配送单",
                    f"{store.name} → {order.address.detail}，运费 ¥{task.fee:.2f}",
                )
        return task

    # ------------------------------------------------------------------ #
    # 骑手操作
    # ------------------------------------------------------------------ #
    def set_online(self, rider_id: str, online: bool) -> Rider:
        rider = self.require_rider(rider_id)
        rider.online = online
        self.repos.users.update(rider)
        self.audit.record(
            actor_id=rider_id,
            actor_role=rider.role.label,
            action="骑手上线" if online else "骑手下线",
            target_type="骑手",
            target_id=rider_id,
        )
        return rider

    def available_tasks(self) -> list[DeliveryTask]:
        tasks = []
        for task in self.repos.deliveries.available():
            order = self.repos.orders.find(task.order_id)
            if order is not None and order.status is OrderStatus.PENDING_DELIVERY:
                tasks.append(task)
        return sorted(tasks, key=lambda t: t.distance_km)

    def my_tasks(self, rider_id: str) -> list[DeliveryTask]:
        self.require_rider(rider_id)
        active = {DeliveryStatus.GRABBED, DeliveryStatus.PICKED}
        tasks = [t for t in self.repos.deliveries.by_rider(rider_id) if t.status in active]
        return sorted(tasks, key=lambda t: t.created_at)

    def task_detail(self, task_id: str) -> tuple[DeliveryTask, Order]:
        task = self.repos.deliveries.get(task_id)
        order = self.repos.orders.get(task.order_id)
        return task, order

    def grab(self, task_id: str, rider_id: str, *, now: datetime | None = None) -> DeliveryTask:
        rider = self.require_rider(rider_id)
        if not rider.online:
            raise ConflictError("请先上线后再抢单")
        with self._lock:
            task = self.repos.deliveries.get(task_id)
            if task.status is not DeliveryStatus.PENDING:
                raise ConflictError("该配送单已被其他骑手接走")
            order = self.repos.orders.get(task.order_id)
            if order.status is not OrderStatus.PENDING_DELIVERY:
                raise ConflictError("订单当前不可接单")
            if len(rider.active_task_ids) >= self.settings.max_rider_active_tasks:
                raise ConflictError("同时进行的配送单已达上限，请先完成手头任务")

            task.status = DeliveryStatus.GRABBED
            task.rider_id = rider_id
            task.grabbed_at = now or datetime.now()
            self.repos.deliveries.update(task)
            rider.active_task_ids.append(task_id)
            self.repos.users.update(rider)

            self.notifications.send(
                order.customer_id,
                "骑手已接单",
                f"骑手 {rider.nickname} 正在赶往 {self.repos.stores.get(order.store_id).name}",
            )
            self.audit.record(
                actor_id=rider_id,
                actor_role=rider.role.label,
                action="抢单",
                target_type="配送单",
                target_id=task_id,
                detail=order.order_id,
            )
            return task

    def pickup(self, task_id: str, rider_id: str, *, now: datetime | None = None) -> DeliveryTask:
        self.require_rider(rider_id)
        with self._lock:
            task = self._own_task(task_id, rider_id)
            if task.status is not DeliveryStatus.GRABBED:
                if task.status is DeliveryStatus.PICKED:
                    return task
                raise ConflictError("当前配送单状态不能确认取餐")
            order = self.repos.orders.get(task.order_id)
            if order.status not in (OrderStatus.PENDING_DELIVERY, OrderStatus.DELIVERING):
                raise ConflictError(f"订单当前为「{order.status.label}」，不能取餐")
            task.status = DeliveryStatus.PICKED
            task.picked_at = now or datetime.now()
            self.repos.deliveries.update(task)
            # 重新派单的订单已处于「配送中」，取餐时不再重复迁移
            if order.status is OrderStatus.PENDING_DELIVERY:
                self.lifecycle.transition(
                    order,
                    OrderStatus.DELIVERING,
                    actor_id=rider_id,
                    actor_role=UserRole.RIDER,
                    note=f"骑手 {rider_id} 确认取餐",
                    now=now,
                )
            self.notifications.send(
                order.customer_id, "餐品已取", "骑手已取餐，正在配送中"
            )
            return task

    def deliver(self, task_id: str, rider_id: str, *, now: datetime | None = None) -> DeliveryTask:
        rider = self.require_rider(rider_id)
        with self._lock:
            task = self._own_task(task_id, rider_id)
            if task.status is DeliveryStatus.DELIVERED:
                return task
            if task.status is not DeliveryStatus.PICKED:
                raise ConflictError("请先确认取餐再确认送达")
            order = self.repos.orders.get(task.order_id)
            task.status = DeliveryStatus.DELIVERED
            task.delivered_at = now or datetime.now()
            self.repos.deliveries.update(task)
            self.lifecycle.transition(
                order,
                OrderStatus.DELIVERED,
                actor_id=rider_id,
                actor_role=UserRole.RIDER,
                note="骑手确认送达",
                now=now,
            )
            rider.completed_count += 1
            if task_id in rider.active_task_ids:
                rider.active_task_ids.remove(task_id)
            self.repos.users.update(rider)
            self.notifications.send(
                order.customer_id, "订单已送达", "请及时确认收货并评价"
            )
            self.notifications.send(
                self.repos.stores.get(order.store_id).merchant_id,
                "订单已送达",
                f"订单 {order.order_id} 已由骑手送达",
            )
            self.audit.record(
                actor_id=rider_id,
                actor_role=rider.role.label,
                action="确认送达",
                target_type="配送单",
                target_id=task_id,
                detail=order.order_id,
            )
            return task

    def report_exception(
        self,
        task_id: str,
        rider_id: str,
        reason: str,
        *,
        now: datetime | None = None,
    ) -> DeliveryTask:
        rider = self.require_rider(rider_id)
        if reason not in EXCEPTION_REASONS:
            raise ValidationError("请选择配送异常原因")
        with self._lock:
            task = self._own_task(task_id, rider_id)
            if task.status is DeliveryStatus.FAILED:
                return task
            if task.status is not DeliveryStatus.PICKED:
                raise ConflictError("确认取餐后才能上报配送异常")
            order = self.repos.orders.get(task.order_id)
            task.status = DeliveryStatus.FAILED
            task.exception_reason = reason
            self.repos.deliveries.update(task)
            if task_id in rider.active_task_ids:
                rider.active_task_ids.remove(task_id)
            self.repos.users.update(rider)
            self.lifecycle.transition(
                order,
                OrderStatus.DELIVERY_FAILED,
                actor_id=rider_id,
                actor_role=UserRole.RIDER,
                note=f"配送异常：{reason}",
                now=now,
            )
            self.notifications.send(
                order.customer_id, "配送遇到问题", f"原因：{reason}，平台将介入处理"
            )
            self.notifications.send_many(
                [admin.user_id for admin in self.repos.users.admins()],
                "配送失败待处理",
                f"订单 {order.order_id}：{reason}",
            )
            return task

    def redispatch(
        self, order_id: str, admin_id: str, rider_id: str, *, now: datetime | None = None
    ) -> DeliveryTask:
        """平台在配送失败后重新派单（状态图 S11 → S5）。"""
        admin = self.require_admin(admin_id)
        rider = self.require_rider(rider_id)
        if not rider.online:
            raise ConflictError("目标骑手当前不在线")
        if len(rider.active_task_ids) >= self.settings.max_rider_active_tasks:
            raise ConflictError("目标骑手同时进行的配送单已达上限")
        with self._lock:
            order = self.repos.orders.get(order_id)
            if order.status is not OrderStatus.DELIVERY_FAILED:
                raise ConflictError("只有配送失败的订单可以重新派单")
            store = self.repos.stores.get(order.store_id)
            old_task = self.repos.deliveries.by_order(order_id)
            distance = distance_km(
                store.x_km, store.y_km, order.address.x_km, order.address.y_km
            )
            task = DeliveryTask(
                task_id=self.repos.db.next_id("DLV"),
                order_id=order_id,
                store_id=order.store_id,
                pickup_text=store.address_text,
                dropoff_text=order.address.detail,
                distance_km=distance,
                fee=order.delivery_fee,
                status=DeliveryStatus.GRABBED,
                rider_id=rider_id,
                grabbed_at=now or datetime.now(),
                dispatch_round=(old_task.dispatch_round + 1) if old_task else 2,
            )
            self.repos.deliveries.add(task)
            rider.active_task_ids.append(task.task_id)
            self.repos.users.update(rider)
            order.delivery_task_id = task.task_id
            self.lifecycle.transition(
                order,
                OrderStatus.DELIVERING,
                actor_id=admin.user_id,
                actor_role=UserRole.ADMIN,
                note=f"平台重新派单给 {rider.nickname}",
                now=now,
            )
            self.notifications.send(
                order.customer_id, "已重新派单", f"骑手 {rider.nickname} 将继续为您配送"
            )
            self.notifications.send(
                rider_id, "平台指派配送单", f"订单 {order_id}，请尽快取餐"
            )
            return task

    def _own_task(self, task_id: str, rider_id: str) -> DeliveryTask:
        task = self.repos.deliveries.get(task_id)
        if task.rider_id != rider_id:
            raise PermissionDeniedError("该配送单不属于当前骑手")
        return task

    # ------------------------------------------------------------------ #
    # 展示辅助
    # ------------------------------------------------------------------ #
    def rider_view(self, task_id: str, rider_id: str) -> dict[str, str]:
        """骑手视图：取餐前隐藏门牌，取餐后显示完整送达地址（REQ-017）。"""
        task = self._own_task(task_id, rider_id)
        order = self.repos.orders.get(task.order_id)
        store = self.repos.stores.get(task.store_id)
        reveal = task.status is DeliveryStatus.PICKED
        return {
            "task_id": task.task_id,
            "order_id": order.order_id,
            "store": store.name,
            "pickup": store.address_text,
            "dropoff": mask_detail(order.address.detail, reveal=reveal),
            "receiver": order.address.receiver,
            "phone": order.address.phone if reveal else mask_phone(order.address.phone),
            "distance": f"{task.distance_km:.2f} km",
            "fee": f"¥{task.fee:.2f}",
        }

    def orders_for_admin(self) -> list[tuple[DeliveryTask, Order]]:
        result = []
        for order in self.repos.orders.by_status(OrderStatus.DELIVERY_FAILED):
            task = self.repos.deliveries.by_order(order.order_id)
            if task:
                result.append((task, order))
        return result
