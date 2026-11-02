"""店铺、菜单、库存与平台审核（REQ-003、REQ-004、REQ-005、REQ-022）。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.enums import DishStatus, StoreStatus, UserRole
from app.domain.models import Category, Dish, Store
from app.domain.pricing import to_money
from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.repository.repositories import Repositories
from app.services.audit import AuditService
from app.services.base import BaseService
from app.services.notifications import NotificationService

REFUND_REASONS = ("缺货", "太忙", "地址太远", "其他")


@dataclass(frozen=True)
class MenuSection:
    category: Category
    dishes: list[Dish]


class StoreService(BaseService):
    def __init__(
        self,
        repos: Repositories,
        settings,
        audit: AuditService,
        notifications: NotificationService,
    ) -> None:
        super().__init__(repos, settings)
        self.audit = audit
        self.notifications = notifications

    # ------------------------------------------------------------------ #
    # 店铺
    # ------------------------------------------------------------------ #
    def apply_store(
        self,
        merchant_id: str,
        *,
        name: str,
        description: str,
        address_text: str,
        x_km: float,
        y_km: float,
        min_order_amount: Decimal | str = "0",
    ) -> Store:
        merchant = self.require_merchant(merchant_id)
        if self.repos.stores.by_merchant(merchant_id):
            raise ConflictError("每个商家账号只能经营一家店铺")
        name = name.strip()
        address_text = address_text.strip()
        if not 2 <= len(name) <= 30:
            raise ValidationError("店铺名称需为 2~30 个字符")
        if len(address_text) < 5:
            raise ValidationError("请填写完整的门店地址")
        if x_km < 0 or y_km < 0:
            raise ValidationError("模拟坐标不能为负数")
        try:
            min_order = to_money(min_order_amount)
        except Exception as exc:  # noqa: BLE001 - Decimal 转换错误统一转为校验错误
            raise ValidationError("起送价格式不正确") from exc
        if min_order < 0:
            raise ValidationError("起送价不能为负数")

        store = Store(
            store_id=self.repos.db.next_id("STR"),
            merchant_id=merchant_id,
            name=name,
            description=description.strip(),
            address_text=address_text,
            x_km=float(x_km),
            y_km=float(y_km),
            status=StoreStatus.PENDING,
            min_order_amount=min_order,
            accept_timeout_minutes=merchant.accept_timeout_minutes,
        )
        self.repos.stores.add(store)
        merchant.store_id = store.store_id
        self.repos.users.update(merchant)
        self.notifications.send_many(
            [admin.user_id for admin in self.repos.users.admins()],
            "新的店铺入驻申请",
            f"{name} 等待资质审核",
        )
        self.audit.record(
            actor_id=merchant_id,
            actor_role=merchant.role.label,
            action="提交店铺入驻申请",
            target_type="店铺",
            target_id=store.store_id,
            detail=name,
        )
        return store

    def store_of_merchant(self, merchant_id: str) -> Store | None:
        return self.repos.stores.by_merchant(merchant_id)

    def store_detail(self, store_id: str) -> Store:
        return self.repos.stores.get(store_id)

    def update_store(
        self,
        merchant_id: str,
        *,
        name: str | None = None,
        notice: str | None = None,
        min_order_amount: Decimal | str | None = None,
        accept_timeout_minutes: int | None = None,
    ) -> Store:
        store = self._require_own_store(merchant_id)
        if name is not None:
            name = name.strip()
            if not 2 <= len(name) <= 30:
                raise ValidationError("店铺名称需为 2~30 个字符")
            store.name = name
        if notice is not None:
            if len(notice) > 100:
                raise ValidationError("公告不能超过 100 个字符")
            store.notice = notice.strip()
        if min_order_amount is not None:
            store.min_order_amount = to_money(min_order_amount)
            if store.min_order_amount < 0:
                raise ValidationError("起送价不能为负数")
        if accept_timeout_minutes is not None:
            store.accept_timeout_minutes = self.settings.clamp_accept_timeout(
                int(accept_timeout_minutes)
            )
            merchant = self.get_user(merchant_id)
            if hasattr(merchant, "accept_timeout_minutes"):
                merchant.accept_timeout_minutes = store.accept_timeout_minutes
                self.repos.users.update(merchant)
        self.repos.stores.update(store)
        self.audit.record(
            actor_id=merchant_id,
            actor_role=UserRole.MERCHANT.label,
            action="修改店铺信息",
            target_type="店铺",
            target_id=store.store_id,
            detail=store.name,
        )
        return store

    def set_business_status(self, merchant_id: str, open_for_business: bool) -> Store:
        store = self._require_own_store(merchant_id)
        if store.status is StoreStatus.SUSPENDED:
            raise PermissionDeniedError("店铺已被平台关停，不能自行恢复营业")
        if store.status is not StoreStatus.OPEN and store.status is not StoreStatus.CLOSED:
            raise ConflictError("店铺尚未通过审核，暂不能营业")
        target = StoreStatus.OPEN if open_for_business else StoreStatus.CLOSED
        if store.status is target:
            return store
        before = store.status
        store.status = target
        self.repos.stores.update(store)
        self.audit.record(
            actor_id=merchant_id,
            actor_role=UserRole.MERCHANT.label,
            action="切换营业状态",
            target_type="店铺",
            target_id=store.store_id,
            detail=f"{before.label} → {target.label}",
        )
        return store

    def _require_own_store(self, merchant_id: str) -> Store:
        self.require_merchant(merchant_id)
        store = self.repos.stores.by_merchant(merchant_id)
        if store is None:
            raise NotFoundError("当前账号尚未创建店铺")
        return store

    # ------------------------------------------------------------------ #
    # 菜单与库存
    # ------------------------------------------------------------------ #
    def menu(self, store_id: str, *, include_unavailable: bool = True) -> list[MenuSection]:
        categories = self.repos.categories.by_store(store_id)
        dishes = self.repos.dishes.by_store(store_id)
        sections: list[MenuSection] = []
        for category in categories:
            items = [d for d in dishes if d.category_id == category.category_id]
            if not include_unavailable:
                items = [d for d in items if d.is_available]
            sections.append(MenuSection(category=category, dishes=items))
        uncategorized = [
            d
            for d in dishes
            if d.category_id not in {c.category_id for c in categories}
        ]
        if uncategorized:
            sections.append(
                MenuSection(
                    category=Category(
                        category_id="",
                        store_id=store_id,
                        name="未分类",
                        sort_no=999,
                    ),
                    dishes=uncategorized,
                )
            )
        return sections

    def add_category(self, merchant_id: str, name: str, sort_no: int = 0) -> Category:
        store = self._require_own_store(merchant_id)
        name = name.strip()
        if not 1 <= len(name) <= 20:
            raise ValidationError("分类名称需为 1~20 个字符")
        if any(c.name == name for c in self.repos.categories.by_store(store.store_id)):
            raise ConflictError("已存在同名分类")
        category = Category(
            category_id=self.repos.db.next_id("CAT"),
            store_id=store.store_id,
            name=name,
            sort_no=sort_no,
        )
        self.repos.categories.add(category)
        return category

    def delete_category(self, merchant_id: str, category_id: str) -> None:
        store = self._require_own_store(merchant_id)
        category = self.repos.categories.get(category_id)
        if category.store_id != store.store_id:
            raise PermissionDeniedError("不能操作其他店铺的分类")
        if any(d.category_id == category_id for d in self.repos.dishes.by_store(store.store_id)):
            raise ConflictError("该分类下仍有菜品，不能删除")
        self.repos.categories.delete(category_id)

    def add_dish(
        self,
        merchant_id: str,
        *,
        category_id: str,
        name: str,
        price: Decimal | str,
        stock: int,
        description: str = "",
    ) -> Dish:
        store = self._require_own_store(merchant_id)
        category = self.repos.categories.get(category_id)
        if category.store_id != store.store_id:
            raise PermissionDeniedError("不能使用其他店铺的分类")
        name = name.strip()
        if not 1 <= len(name) <= 30:
            raise ValidationError("菜品名称需为 1~30 个字符")
        price_money = self._validate_price(price)
        stock = self._validate_stock(stock)
        status = DishStatus.ON_SALE if stock > 0 else DishStatus.SOLD_OUT
        dish = Dish(
            dish_id=self.repos.db.next_id("DSH"),
            store_id=store.store_id,
            category_id=category_id,
            name=name,
            price=price_money,
            stock=stock,
            description=description.strip(),
            status=status,
        )
        self.repos.dishes.add(dish)
        self.audit.record(
            actor_id=merchant_id,
            actor_role=UserRole.MERCHANT.label,
            action="新增菜品",
            target_type="菜品",
            target_id=dish.dish_id,
            detail=f"{name} ¥{price_money}",
        )
        return dish

    def update_dish(
        self,
        merchant_id: str,
        dish_id: str,
        *,
        name: str | None = None,
        price: Decimal | str | None = None,
        stock: int | None = None,
        description: str | None = None,
        category_id: str | None = None,
    ) -> Dish:
        store = self._require_own_store(merchant_id)
        dish = self.repos.dishes.get(dish_id)
        if dish.store_id != store.store_id:
            raise PermissionDeniedError("不能修改其他店铺的菜品")
        changes: list[str] = []
        if name is not None:
            name = name.strip()
            if not 1 <= len(name) <= 30:
                raise ValidationError("菜品名称需为 1~30 个字符")
            changes.append(f"名称 {dish.name} → {name}")
            dish.name = name
        if price is not None:
            new_price = self._validate_price(price)
            changes.append(f"价格 {dish.price} → {new_price}")
            dish.price = new_price
        if stock is not None:
            new_stock = self._validate_stock(stock)
            changes.append(f"库存 {dish.stock} → {new_stock}")
            dish.stock = new_stock
            if dish.status is DishStatus.OFF_SHELF:
                pass
            elif new_stock == 0:
                dish.status = DishStatus.SOLD_OUT
            elif dish.status is DishStatus.SOLD_OUT:
                dish.status = DishStatus.ON_SALE
        if description is not None:
            dish.description = description.strip()
        if category_id is not None:
            category = self.repos.categories.get(category_id)
            if category.store_id != store.store_id:
                raise PermissionDeniedError("不能使用其他店铺的分类")
            dish.category_id = category_id
        self.repos.dishes.update(dish)
        if changes:
            self.audit.record(
                actor_id=merchant_id,
                actor_role=UserRole.MERCHANT.label,
                action="修改菜品",
                target_type="菜品",
                target_id=dish.dish_id,
                detail="；".join(changes),
            )
        return dish

    def set_dish_status(
        self, merchant_id: str, dish_id: str, status: DishStatus
    ) -> Dish:
        store = self._require_own_store(merchant_id)
        dish = self.repos.dishes.get(dish_id)
        if dish.store_id != store.store_id:
            raise PermissionDeniedError("不能操作其他店铺的菜品")
        if status is DishStatus.ON_SALE and dish.stock <= 0:
            raise ConflictError("库存为 0，补货后才能上架")
        dish.status = status
        self.repos.dishes.update(dish)
        self.audit.record(
            actor_id=merchant_id,
            actor_role=UserRole.MERCHANT.label,
            action="调整菜品状态",
            target_type="菜品",
            target_id=dish_id,
            detail=f"{dish.name} → {status.label}",
        )
        return dish

    def _validate_price(self, price: Decimal | str) -> Decimal:
        try:
            value = to_money(price)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError("价格格式不正确") from exc
        if value <= 0:
            raise ValidationError("价格必须大于 0")
        if value > Decimal("9999.99"):
            raise ValidationError("价格超出合理范围")
        return value

    def _validate_stock(self, stock: int) -> int:
        try:
            value = int(stock)
        except (TypeError, ValueError) as exc:
            raise ValidationError("库存必须为整数") from exc
        if value < 0:
            raise ValidationError("库存不能为负数")
        if value > 9999:
            raise ValidationError("库存超出上限")
        return value

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def search_stores(
        self,
        keyword: str = "",
        *,
        only_open: bool = True,
        sort_by: str = "rating",
    ) -> list[Store]:
        keyword = keyword.strip()
        dish_store_ids = (
            {d.store_id for d in self.repos.dishes.search(keyword)} if keyword else set()
        )
        results = []
        for store in self.repos.stores.all():
            if only_open and not store.is_open:
                continue
            if keyword and keyword not in store.name and store.store_id not in dish_store_ids:
                continue
            results.append(store)
        if sort_by == "min_order":
            results.sort(key=lambda s: (s.min_order_amount, -s.rating))
        else:
            results.sort(key=lambda s: (-s.rating, s.name))
        return results

    def dishes_of_store(self, store_id: str, *, only_available: bool = False) -> list[Dish]:
        dishes = self.repos.dishes.by_store(store_id)
        return [d for d in dishes if d.is_available] if only_available else dishes

    def category_of_dish(self, dish_id: str) -> Category | None:
        dish = self.repos.dishes.find(dish_id)
        return self.repos.categories.find(dish.category_id) if dish else None

    # ------------------------------------------------------------------ #
    # 平台审核与处置
    # ------------------------------------------------------------------ #
    def pending_stores(self, admin_id: str) -> list[Store]:
        self.require_admin(admin_id)
        return [s for s in self.repos.stores.all() if s.status is StoreStatus.PENDING]

    def approve_store(self, admin_id: str, store_id: str) -> Store:
        admin = self.require_admin(admin_id)
        store = self.repos.stores.get(store_id)
        if store.status is not StoreStatus.PENDING:
            raise ConflictError("该店铺不在待审核状态")
        store.status = StoreStatus.OPEN
        self.repos.stores.update(store)
        self.notifications.send(store.merchant_id, "店铺审核通过", f"{store.name} 已可开始营业")
        self.audit.record(
            actor_id=admin.user_id,
            actor_role=admin.role.label,
            action="审核通过店铺",
            target_type="店铺",
            target_id=store_id,
            detail=store.name,
        )
        return store

    def reject_store(self, admin_id: str, store_id: str, reason: str) -> Store:
        admin = self.require_admin(admin_id)
        if not reason.strip():
            raise ValidationError("审核不通过必须填写原因")
        store = self.repos.stores.get(store_id)
        if store.status is not StoreStatus.PENDING:
            raise ConflictError("该店铺不在待审核状态")
        store.status = StoreStatus.REJECTED
        self.repos.stores.update(store)
        self.notifications.send(store.merchant_id, "店铺审核未通过", reason.strip())
        self.audit.record(
            actor_id=admin.user_id,
            actor_role=admin.role.label,
            action="审核驳回店铺",
            target_type="店铺",
            target_id=store_id,
            detail=reason.strip(),
        )
        return store

    def suspend_store(self, admin_id: str, store_id: str, reason: str) -> Store:
        admin = self.require_admin(admin_id)
        if not reason.strip():
            raise ValidationError("请填写关停原因")
        store = self.repos.stores.get(store_id)
        if store.status is StoreStatus.SUSPENDED:
            return store
        if store.status is StoreStatus.PENDING:
            raise ConflictError("待审核店铺不能关停，请先审核")
        before = store.status
        store.status = StoreStatus.SUSPENDED
        self.repos.stores.update(store)
        self.notifications.send(store.merchant_id, "店铺已被平台关停", reason.strip())
        self.audit.record(
            actor_id=admin.user_id,
            actor_role=admin.role.label,
            action="关停店铺",
            target_type="店铺",
            target_id=store_id,
            detail=f"{before.label} → 已关停：{reason.strip()}",
        )
        return store

    def restore_store(self, admin_id: str, store_id: str) -> Store:
        admin = self.require_admin(admin_id)
        store = self.repos.stores.get(store_id)
        if store.status is not StoreStatus.SUSPENDED:
            raise ConflictError("该店铺未被关停")
        store.status = StoreStatus.CLOSED
        self.repos.stores.update(store)
        self.notifications.send(store.merchant_id, "店铺恢复经营", "平台已解除关停，可自行恢复营业")
        self.audit.record(
            actor_id=admin.user_id,
            actor_role=admin.role.label,
            action="解除店铺关停",
            target_type="店铺",
            target_id=store_id,
        )
        return store
