"""用户、收货地址与账号处置（REQ-001、REQ-002、REQ-014、REQ-022）。"""

from __future__ import annotations

from app.domain.enums import AccountStatus, UserRole
from app.domain.models import Address, User
from app.exceptions import PermissionDeniedError, ValidationError
from app.repository.repositories import Repositories
from app.services.audit import AuditService
from app.services.base import BaseService
from app.services.notifications import NotificationService
from app.services.privacy import is_valid_phone


class UserService(BaseService):
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
    # 资料
    # ------------------------------------------------------------------ #
    def profile(self, user_id: str) -> User:
        return self.get_user(user_id)

    def update_nickname(self, user_id: str, nickname: str) -> User:
        nickname = nickname.strip()
        if not 1 <= len(nickname) <= 20:
            raise ValidationError("昵称长度需为 1~20 个字符")
        user = self.require_user(user_id)
        before = user.nickname
        user.nickname = nickname
        self.repos.users.update(user)
        self.audit.record(
            actor_id=user_id,
            actor_role=user.role.label,
            action="修改资料",
            target_type="用户",
            target_id=user_id,
            detail=f"昵称：{before} → {nickname}",
        )
        return user

    # ------------------------------------------------------------------ #
    # 收货地址
    # ------------------------------------------------------------------ #
    def list_addresses(self, customer_id: str) -> list[Address]:
        self.require_customer(customer_id)
        return self.repos.addresses.by_customer(customer_id)

    def add_address(
        self,
        customer_id: str,
        *,
        receiver: str,
        phone: str,
        detail: str,
        x_km: float,
        y_km: float,
        set_default: bool = False,
    ) -> Address:
        customer = self.require_customer(customer_id)
        receiver, detail = receiver.strip(), detail.strip()
        if not receiver:
            raise ValidationError("请填写收货人")
        if not is_valid_phone(phone):
            raise ValidationError("请填写有效的联系电话")
        if len(detail) < 5:
            raise ValidationError("收货地址需详细到楼栋门牌")
        if x_km < 0 or y_km < 0:
            raise ValidationError("模拟坐标不能为负数")

        addresses = self.repos.addresses.by_customer(customer_id)
        is_default = set_default or not addresses
        address = Address(
            address_id=self.repos.db.next_id("ADR"),
            customer_id=customer_id,
            receiver=receiver,
            phone=phone.strip(),
            detail=detail,
            x_km=float(x_km),
            y_km=float(y_km),
            is_default=is_default,
        )
        if is_default:
            self._clear_default(addresses)
            customer.default_address_id = address.address_id
            self.repos.users.update(customer)
        self.repos.addresses.add(address)
        self.audit.record(
            actor_id=customer_id,
            actor_role=UserRole.CUSTOMER.label,
            action="新增收货地址",
            target_type="地址",
            target_id=address.address_id,
            detail=detail,
        )
        return address

    def update_address(
        self,
        customer_id: str,
        address_id: str,
        *,
        receiver: str,
        phone: str,
        detail: str,
        x_km: float,
        y_km: float,
    ) -> Address:
        self.require_customer(customer_id)
        address = self.repos.addresses.get(address_id)
        if address.customer_id != customer_id:
            raise PermissionDeniedError("不能修改他人的收货地址")
        if not receiver.strip() or not detail.strip():
            raise ValidationError("收货人与详细地址不能为空")
        if not is_valid_phone(phone):
            raise ValidationError("请填写有效的联系电话")
        address.receiver = receiver.strip()
        address.phone = phone.strip()
        address.detail = detail.strip()
        address.x_km = float(x_km)
        address.y_km = float(y_km)
        self.repos.addresses.update(address)
        return address

    def delete_address(self, customer_id: str, address_id: str) -> None:
        customer = self.require_customer(customer_id)
        address = self.repos.addresses.get(address_id)
        if address.customer_id != customer_id:
            raise PermissionDeniedError("不能删除他人的收货地址")
        self.repos.addresses.delete(address_id)
        if customer.default_address_id == address_id:
            remaining = self.repos.addresses.by_customer(customer_id)
            customer.default_address_id = remaining[0].address_id if remaining else None
            self.repos.users.update(customer)

    def set_default_address(self, customer_id: str, address_id: str) -> Address:
        customer = self.require_customer(customer_id)
        address = self.repos.addresses.get(address_id)
        if address.customer_id != customer_id:
            raise PermissionDeniedError("不能操作他人的收货地址")
        self._clear_default(self.repos.addresses.by_customer(customer_id))
        address.is_default = True
        self.repos.addresses.update(address)
        customer.default_address_id = address_id
        self.repos.users.update(customer)
        return address

    def _clear_default(self, addresses: list[Address]) -> None:
        for item in addresses:
            if item.is_default:
                item.is_default = False
                self.repos.addresses.update(item)

    def default_address(self, customer_id: str) -> Address | None:
        customer = self.require_customer(customer_id)
        address = self.repos.addresses.find(customer.default_address_id)
        if address:
            return address
        addresses = self.repos.addresses.by_customer(customer_id)
        return addresses[0] if addresses else None

    # ------------------------------------------------------------------ #
    # 平台处置（仅管理员）
    # ------------------------------------------------------------------ #
    def list_users(self, admin_id: str, *, role: UserRole | None = None) -> list[User]:
        self.require_admin(admin_id)
        users = self.repos.users.all()
        return [u for u in users if role is None or u.role is role]

    def freeze_user(self, admin_id: str, user_id: str, reason: str) -> User:
        admin = self.require_admin(admin_id)
        target = self.get_user(user_id)
        if target.role is UserRole.ADMIN:
            raise PermissionDeniedError("不能冻结平台管理员账号")
        if target.status is AccountStatus.FROZEN:
            return target
        if not reason.strip():
            raise ValidationError("请填写冻结原因")
        target.status = AccountStatus.FROZEN
        self.repos.users.update(target)
        self.notifications.send(user_id, "账号已被冻结", f"原因：{reason}")
        self.audit.record(
            actor_id=admin.user_id,
            actor_role=admin.role.label,
            action="冻结账号",
            target_type="用户",
            target_id=user_id,
            detail=reason,
        )
        return target

    def unfreeze_user(self, admin_id: str, user_id: str) -> User:
        admin = self.require_admin(admin_id)
        target = self.get_user(user_id)
        if target.status is AccountStatus.ACTIVE:
            return target
        target.status = AccountStatus.ACTIVE
        self.repos.users.update(target)
        self.notifications.send(user_id, "账号已恢复", "平台已解除冻结")
        self.audit.record(
            actor_id=admin.user_id,
            actor_role=admin.role.label,
            action="解除冻结",
            target_type="用户",
            target_id=user_id,
        )
        return target
