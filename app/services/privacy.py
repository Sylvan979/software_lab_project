"""个人信息脱敏（REQ-017）。

商家与骑手看到的手机号、门牌信息必须脱敏；骑手仅在取餐后可看到完整送达地址。
"""

from __future__ import annotations

import re

PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) != 11:
        return phone
    return f"{digits[:3]}****{digits[-4:]}"


def mask_detail(detail: str, *, reveal: bool) -> str:
    """未到允许查看时间时，只显示小区/楼栋前两级地址。"""
    if reveal:
        return detail
    parts = re.split(r"[号栋幢座室\s]+", detail)
    visible = [part for part in parts if part][:2]
    return "".join(visible) + "****" if visible else "****"


def is_valid_phone(phone: str) -> bool:
    return bool(PHONE_PATTERN.match(phone.strip()))
