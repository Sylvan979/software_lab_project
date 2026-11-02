"""服务层基类与通用工具。"""

from __future__ import annotations

import threading
from datetime import datetime

from app.config import Settings
from app.domain.enums import AccountStatus, UserRole
from app.domain.models import User
from app.exceptions import AuthenticationError, NotFoundError, PermissionDeniedError
from app.repository.repositories import Repositories


def now_or_default(value: datetime | None = None) -> datetime:
    return value or datetime.now()


class BaseService:
    """持有仓储与配置，提供鉴权辅助方法。

    ``self._lock`` 为可重入锁：Tkinter 定时任务与按钮回调可能并发调用服务。
    """

    def __init__(self, repos: Repositories, settings: Settings) -> None:
        self.repos = repos
        self.settings = settings
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # 鉴权
    # ------------------------------------------------------------------ #
    def get_user(self, user_id: str) -> User:
        try:
            return self.repos.users.get(user_id)
        except NotFoundError as exc:
            raise AuthenticationError("用户不存在或已被删除") from exc

    def require_user(self, user_id: str) -> User:
        user = self.get_user(user_id)
        if not user.is_active:
            raise AuthenticationError("账号已被冻结，请联系平台管理员")
        return user

    def require_role(self, user_id: str, *roles: UserRole) -> User:
        user = self.require_user(user_id)
        if user.role not in roles:
            raise PermissionDeniedError(
                f"当前角色「{user.role.label}」无权执行该操作"
            )
        return user

    def require_admin(self, user_id: str) -> User:
        return self.require_role(user_id, UserRole.ADMIN)

    def require_merchant(self, user_id: str) -> User:
        return self.require_role(user_id, UserRole.MERCHANT)

    def require_customer(self, user_id: str) -> User:
        return self.require_role(user_id, UserRole.CUSTOMER)

    def require_rider(self, user_id: str) -> User:
        return self.require_role(user_id, UserRole.RIDER)

    def assert_active(self, user: User) -> None:
        if user.status is AccountStatus.FROZEN:
            raise AuthenticationError("账号已被冻结，请联系平台管理员")
