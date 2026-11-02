"""注册、验证码登录与会话管理（REQ-001）。

本期不接短信网关：验证码固定为演示码，错误 5 次锁定 10 分钟。
会话只保存在内存，程序退出即失效；数据库只存账号本身。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.enums import UserRole
from app.domain.models import Cart, Customer, Merchant, Rider, User
from app.exceptions import (
    AuthenticationError,
    ConflictError,
    PermissionDeniedError,
    ValidationError,
)
from app.repository.repositories import Repositories
from app.services.audit import AuditService
from app.services.base import BaseService
from app.services.privacy import is_valid_phone


@dataclass(frozen=True)
class Session:
    token: str
    user_id: str
    role: UserRole
    created_at: datetime
    expires_at: datetime


@dataclass
class _LoginState:
    attempts: int = 0
    locked_until: datetime | None = None


class AuthService(BaseService):
    def __init__(self, repos: Repositories, settings, audit: AuditService) -> None:
        super().__init__(repos, settings)
        self.audit = audit
        self._sessions: dict[str, Session] = {}
        self._login_states: dict[str, _LoginState] = {}
        self._codes: dict[str, tuple[str, datetime]] = {}

    # ------------------------------------------------------------------ #
    # 验证码
    # ------------------------------------------------------------------ #
    def request_code(self, phone: str) -> str:
        if not is_valid_phone(phone):
            raise ValidationError("请输入 11 位有效手机号")
        return self.settings.demo_code

    def _check_code(self, phone: str, code: str, now: datetime) -> None:
        state = self._login_states.setdefault(phone, _LoginState())
        if state.locked_until and now < state.locked_until:
            minutes = max(1, int((state.locked_until - now).total_seconds() // 60) + 1)
            raise AuthenticationError(f"验证码错误次数过多，请 {minutes} 分钟后再试")

        stored = self._codes.get(phone)
        valid_codes = {self.settings.demo_code}
        if stored and now < stored[1]:
            valid_codes.add(stored[0])
        if code not in valid_codes:
            state.attempts += 1
            if state.attempts >= self.settings.login_max_attempts:
                state.attempts = 0
                state.locked_until = now + timedelta(minutes=self.settings.login_lock_minutes)
                raise AuthenticationError("验证码错误次数过多，账号已锁定 10 分钟")
            remaining = self.settings.login_max_attempts - state.attempts
            raise AuthenticationError(f"验证码错误，还可尝试 {remaining} 次")

        state.attempts = 0
        state.locked_until = None
        self._codes.pop(phone, None)

    # ------------------------------------------------------------------ #
    # 注册与登录
    # ------------------------------------------------------------------ #
    def register(
        self,
        phone: str,
        nickname: str,
        role: UserRole,
        code: str,
        *,
        now: datetime | None = None,
    ) -> User:
        now = now or datetime.now()
        phone = phone.strip()
        nickname = nickname.strip()
        if not is_valid_phone(phone):
            raise ValidationError("请输入 11 位有效手机号")
        if not 1 <= len(nickname) <= 20:
            raise ValidationError("昵称长度需为 1~20 个字符")
        if role is UserRole.ADMIN:
            raise PermissionDeniedError("平台管理员账号由系统预置，不开放注册")
        if role not in (UserRole.CUSTOMER, UserRole.MERCHANT, UserRole.RIDER):
            raise ValidationError("请选择顾客、商家或配送员角色")
        if self.repos.users.find_by_phone(phone):
            raise ConflictError("该手机号已注册，请直接登录")
        self._check_code(phone, code, now)

        user_id = self.repos.db.next_id("USR")
        common = {"user_id": user_id, "phone": phone, "nickname": nickname}
        if role is UserRole.CUSTOMER:
            user: User = Customer(**common)
            self.repos.carts.add(Cart(cart_id=self.repos.db.next_id("CRT"), customer_id=user_id))
        elif role is UserRole.MERCHANT:
            user = Merchant(
                **common,
                accept_timeout_minutes=self.settings.default_accept_timeout_minutes,
            )
        else:
            user = Rider(**common, employee_no=f"R{user_id.split('-')[-1]}", online=False)
        self.repos.users.add(user)
        self.audit.record(
            actor_id=user_id,
            actor_role=role.label,
            action="注册账号",
            target_type="用户",
            target_id=user_id,
            detail=f"{nickname}（{role.label}）",
        )
        return user

    def login(
        self,
        phone: str,
        code: str,
        *,
        now: datetime | None = None,
    ) -> Session:
        now = now or datetime.now()
        phone = phone.strip()
        user = self.repos.users.find_by_phone(phone)
        if user is None:
            raise AuthenticationError("该手机号尚未注册")
        if not user.is_active:
            raise AuthenticationError("账号已被冻结，请联系平台管理员")
        self._check_code(phone, code.strip(), now)

        token = secrets.token_urlsafe(24)
        session = Session(
            token=token,
            user_id=user.user_id,
            role=user.role,
            created_at=now,
            expires_at=now + timedelta(hours=8),
        )
        self._sessions[token] = session
        self.audit.record(
            actor_id=user.user_id,
            actor_role=user.role.label,
            action="登录",
            target_type="用户",
            target_id=user.user_id,
        )
        return session

    def logout(self, token: str) -> None:
        self._sessions.pop(token, None)

    def current_user(self, token: str, *, now: datetime | None = None) -> User:
        now = now or datetime.now()
        session = self._sessions.get(token)
        if session is None:
            raise AuthenticationError("登录状态已失效，请重新登录")
        if now >= session.expires_at:
            self._sessions.pop(token, None)
            raise AuthenticationError("登录已过期，请重新登录")
        return self.require_user(session.user_id)

    def session_of(self, token: str) -> Session:
        session = self._sessions.get(token)
        if session is None:
            raise AuthenticationError("登录状态已失效，请重新登录")
        return session
