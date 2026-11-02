"""程序入口：启动桌面应用。"""

from __future__ import annotations

import sys


def main() -> int:
    from app.ui.app import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
