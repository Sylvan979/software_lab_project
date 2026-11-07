"""程序入口：启动桌面应用。"""

from __future__ import annotations

import sys

MIN_PYTHON = (3, 11)


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        current = ".".join(str(part) for part in sys.version_info[:3])
        sys.stderr.write(
            f"本程序需要 Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 或更高版本，"
            f"当前解释器为 {current}。\n"
            "请使用 `python run.py`、`py -3.14 run.py` 或完整的 3.11+ 解释器路径运行。\n"
        )
        return 1

    from app.ui.app import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
