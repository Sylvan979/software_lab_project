"""基于 JSON 文件的轻量数据库。

- 每次提交整体写入临时文件后原子替换，避免进程中断产生半个文件；
- ``transaction()`` 内的多次写操作合并为一次落盘；
- 主键由持久化计数器生成，重启后不会重号。
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.exceptions import StorageError

SCHEMA_VERSION = 1


class JsonDatabase:
    def __init__(self, path: Path, *, autosave: bool = True) -> None:
        self.path = Path(path)
        self.autosave = autosave
        self._lock = threading.RLock()
        self._depth = 0
        self._dirty = False
        self._tables: dict[str, dict[str, dict[str, Any]]] = {}
        self._counters: dict[str, int] = {}
        self.load()

    # ------------------------------------------------------------------ #
    # 读写
    # ------------------------------------------------------------------ #
    def load(self) -> None:
        with self._lock:
            self._tables = {}
            self._counters = {}
            if not self.path.exists():
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise StorageError(f"数据文件无法读取：{self.path}（{exc}）") from exc
            self._tables = raw.get("tables", {})
            self._counters = raw.get("counters", {})

    def save(self) -> None:
        """显式落盘；``autosave`` 只影响 ``mark_dirty`` 是否自动调用本方法。"""
        with self._lock:
            payload = {
                "schema_version": SCHEMA_VERSION,
                "counters": self._counters,
                "tables": self._tables,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            try:
                temp_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                self._replace_with_retry(temp_path)
            except OSError as exc:
                raise StorageError(f"数据写入失败：{exc}") from exc
            self._dirty = False

    def _replace_with_retry(self, temp_path, attempts: int = 4) -> None:
        """Windows 上杀毒/索引服务可能短暂占用目标文件，重试原子替换。"""
        for attempt in range(attempts):
            try:
                os.replace(temp_path, self.path)
                return
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def mark_dirty(self) -> None:
        with self._lock:
            self._dirty = True
            if self._depth == 0 and self.autosave:
                self.save()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """把一组写操作合并为一次持久化，异常时仍尽力保存已完成的变更。"""
        with self._lock:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
                if self._depth == 0 and self._dirty:
                    self.save()

    # ------------------------------------------------------------------ #
    # 表与主键
    # ------------------------------------------------------------------ #
    def table(self, name: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            return self._tables.setdefault(name, {})

    def next_id(self, prefix: str) -> str:
        with self._lock:
            current = self._counters.get(prefix, 0) + 1
            self._counters[prefix] = current
            self.mark_dirty()
            return f"{prefix}-{current:04d}"

    def clear(self) -> None:
        """仅用于测试与演示数据重建。"""
        with self._lock:
            self._tables.clear()
            self._counters.clear()
            self.mark_dirty()
