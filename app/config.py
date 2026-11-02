"""全局配置：路径、超时时限与计费规则。

所有时限与金额集中于此，服务层不得硬编码魔法数字；
测试通过传入自定义 ``Settings`` 覆盖，例如把接单时限改为 0 秒。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = APP_ROOT / "data"


@dataclass(frozen=True)
class Settings:
    """不可变配置对象。"""

    data_dir: Path = DEFAULT_DATA_DIR

    # 订单相关时限（分钟）
    payment_timeout_minutes: int = 15
    default_accept_timeout_minutes: int = 10
    accept_timeout_min_range: int = 5
    accept_timeout_max_range: int = 20
    refund_timeout_minutes: int = 10
    dispatch_timeout_minutes: int = 3
    auto_complete_hours: int = 24
    customer_response_minutes: int = 15

    # 配送与计价
    delivery_radius_km: float = 3.0
    delivery_base_fee: Decimal = Decimal("5.00")
    delivery_per_km_fee: Decimal = Decimal("1.00")
    packing_fee: Decimal = Decimal("1.00")
    max_rider_active_tasks: int = 3
    dispatch_max_rounds: int = 3

    # 登录与验证码
    demo_code: str = "123456"
    code_ttl_minutes: int = 5
    login_max_attempts: int = 5
    login_lock_minutes: int = 10

    # 持久化
    autosave: bool = True

    def db_path(self) -> Path:
        return self.data_dir / "platform.json"

    def clamp_accept_timeout(self, minutes: int) -> int:
        """商家设置的接单时限收敛到 [5, 20] 分钟（REQ-019）。"""
        return max(self.accept_timeout_min_range, min(self.accept_timeout_max_range, minutes))


DEFAULT_SETTINGS = Settings()
