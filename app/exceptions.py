"""领域异常体系。

服务层只抛出 ``DomainError`` 子类，界面层统一捕获并展示 ``message``；
错误码便于日志检索与测试断言。
"""

from __future__ import annotations


class DomainError(Exception):
    """所有可预期业务错误的基类。"""

    code = "DOMAIN_ERROR"

    def __init__(self, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        return self.message


class ValidationError(DomainError):
    code = "VALIDATION_ERROR"


class NotFoundError(DomainError):
    code = "NOT_FOUND"


class PermissionDeniedError(DomainError):
    code = "PERMISSION_DENIED"


class AuthenticationError(DomainError):
    code = "AUTHENTICATION_ERROR"


class ConflictError(DomainError):
    code = "CONFLICT"


class InsufficientStockError(ConflictError):
    code = "INSUFFICIENT_STOCK"

    def __init__(self, dishes: list[str]) -> None:
        self.dishes = dishes
        super().__init__("以下菜品已售罄或库存不足：" + "、".join(dishes))


class InvalidTransitionError(ConflictError):
    code = "INVALID_TRANSITION"

    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(f"订单不能从「{current}」变更为「{target}」")


class OutOfRangeError(ValidationError):
    code = "OUT_OF_RANGE"


class PaymentError(DomainError):
    code = "PAYMENT_ERROR"


class IdempotencyConflictError(ConflictError):
    code = "IDEMPOTENCY_CONFLICT"


class StorageError(DomainError):
    code = "STORAGE_ERROR"
