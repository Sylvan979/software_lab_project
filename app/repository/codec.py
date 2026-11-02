"""领域对象与 JSON 之间的编解码。

不引入 ORM：实体均为 dataclass，按字段类型递归编码；
枚举、Decimal、datetime 使用带标记的字典表示，避免精度与类型丢失。
``_type`` 字段用于识别 ``User`` 表中的顾客/商家/骑手/管理员子类。
"""

from __future__ import annotations

import types
import typing
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, get_args, get_origin, get_type_hints

import app.domain.enums as enums_module
import app.domain.models as models_module

TYPE_REGISTRY: dict[str, type] = {
    name: obj
    for name, obj in vars(models_module).items()
    if isinstance(obj, type) and is_dataclass(obj)
}
ENUM_REGISTRY: dict[str, type[Enum]] = {
    name: obj
    for name, obj in vars(enums_module).items()
    if isinstance(obj, type) and issubclass(obj, Enum) and obj is not Enum
}

_HINT_CACHE: dict[type, dict[str, Any]] = {}


def _hints(cls: type) -> dict[str, Any]:
    cached = _HINT_CACHE.get(cls)
    if cached is None:
        cached = get_type_hints(cls)
        _HINT_CACHE[cls] = cached
    return cached


def encode(value: Any) -> Any:
    """把领域对象转换为可 JSON 序列化的结构。"""
    if isinstance(value, Enum):
        return {"__enum__": f"{type(value).__name__}.{value.name}"}
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if is_dataclass(value) and not isinstance(value, type):
        data: dict[str, Any] = {"_type": type(value).__name__}
        for f in fields(value):
            data[f.name] = encode(getattr(value, f.name))
        return data
    if isinstance(value, dict):
        return {str(key): encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(item) for item in value]
    return value


def _decode_marker(value: dict[str, Any]) -> Any:
    if "__enum__" in value:
        qualified = value["__enum__"]
        enum_name, member_name = qualified.split(".", 1)
        enum_cls = ENUM_REGISTRY.get(enum_name)
        if enum_cls is None:
            raise ValueError(f"未知枚举类型：{enum_name}")
        return enum_cls[member_name]
    if "__decimal__" in value:
        return Decimal(value["__decimal__"])
    if "__datetime__" in value:
        return datetime.fromisoformat(value["__datetime__"])
    return _UNSET


_UNSET = object()


def decode(value: Any, hint: Any = Any) -> Any:
    """按字段类型提示还原领域对象。"""
    if isinstance(value, dict):
        marker = _decode_marker(value)
        if marker is not _UNSET:
            return marker

    if get_origin(hint) is typing.Union or isinstance(hint, types.UnionType):
        args = [arg for arg in get_args(hint) if arg is not type(None)]
        hint = args[0] if args else Any

    if is_dataclass(hint) and isinstance(value, dict):
        cls = TYPE_REGISTRY.get(value.get("_type", ""), hint)
        if not is_dataclass(cls):
            cls = hint
        hints = _hints(cls)
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if not f.init or f.name not in value:
                continue
            kwargs[f.name] = decode(value[f.name], hints.get(f.name, Any))
        return cls(**kwargs)

    if isinstance(value, dict):
        args = get_args(hint)
        key_hint, value_hint = (args + (Any, Any))[:2] if args else (Any, Any)
        return {
            decode(key, key_hint) if key_hint is not str else key: decode(item, value_hint)
            for key, item in value.items()
        }

    if isinstance(value, list):
        args = get_args(hint)
        item_hint = args[0] if args else Any
        return [decode(item, item_hint) for item in value]

    if isinstance(hint, type) and issubclass(hint, Enum) and isinstance(value, str):
        return hint(value)
    return value
