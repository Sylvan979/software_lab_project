"""开发辅助：启动应用并截取各角色主界面，用于实验报告。

依赖：Pillow（仅开发期）。运行：python tools/capture_screenshots.py
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.domain.enums import OrderStatus  # noqa: E402  # pylint: disable=wrong-import-position
from app.ui.app import MainApp  # noqa: E402  # pylint: disable=wrong-import-position

OUTPUT = ROOT / "docs" / "screenshots"


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def snap(app: MainApp, name: str) -> None:
    app.update_idletasks()
    app.update()
    time.sleep(0.4)
    app.update()
    hwnd = int(app.wm_frame(), 16)
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)
    rect = _Rect()
    ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = _Point(rect.left, rect.top)
    ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(origin))
    # Tk 进程按逻辑像素工作，屏幕截图使用物理像素，需要按系统缩放换算
    screen_scale = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0
    image = ImageGrab.grab(
        bbox=(
            int(origin.x * screen_scale),
            int(origin.y * screen_scale),
            int((origin.x + rect.right - rect.left) * screen_scale),
            int((origin.y + rect.bottom - rect.top) * screen_scale),
        )
    )
    image.save(OUTPUT / name)
    print("saved", name, image.size)


def ensure_hall_task(app: MainApp) -> None:
    """确保接单大厅有单可抢、骑手手上有单，便于截图。"""
    ctx = app.ctx
    from app.cli import ensure_demo_data  # pylint: disable=import-outside-toplevel

    ids = ensure_demo_data(ctx)
    uid = ids["customer"]
    address = ctx.users.default_address(uid)
    if address is None:
        return

    def ready_order() -> None:
        ctx.cart.clear(uid)
        ctx.cart.add_item(uid, ids["dish_a_hot"], 2)
        order = ctx.orders.checkout(uid, address.address_id).order
        ctx.orders.pay(order.order_id, uid)
        ctx.orders.merchant_accept(order.order_id, ids["merchant_a"])
        ctx.orders.mark_ready(order.order_id, ids["merchant_a"])

    if not ctx.delivery.available_tasks():
        ready_order()
    if not ctx.delivery.my_tasks(ids["rider"]):
        ready_order()
        task = ctx.delivery.available_tasks()[-1]
        ctx.delivery.grab(task.task_id, ids["rider"])


def ensure_pending_refund(app: MainApp):
    """仲裁页需要有单可处理，截完图后由商家驳回恢复订单状态。"""
    from app.cli import ensure_demo_data  # pylint: disable=import-outside-toplevel

    ctx = app.ctx
    ensure_demo_data(ctx)
    for order in ctx.repos.orders.by_status(
        OrderStatus.PENDING_DELIVERY, OrderStatus.DELIVERING
    ):
        if ctx.repos.refunds.by_order(order.order_id) is None:
            return ctx.refunds.apply(order.order_id, order.customer_id, "餐品撒漏，申请退款")
    return None


def dismiss_refund(app: MainApp, refund) -> None:
    if refund is None:
        return
    from app.cli import ensure_demo_data  # pylint: disable=import-outside-toplevel

    ctx = app.ctx
    merchant_id = ensure_demo_data(ctx)["merchant_a"]
    ctx.refunds.merchant_handle(
        refund.refund_id, merchant_id, approve=False, comment="演示截图结束，撤回"
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    app = MainApp()
    app.geometry("1200x820+20+20")
    app.attributes("-topmost", True)
    app.lift()
    ensure_hall_task(app)
    snap(app, "01-login.png")

    shots = (
        ("13800000001", 0, "02-customer-menu.png"),
        ("13800000001", 2, "03-customer-orders.png"),
        ("13900000001", 2, "04-merchant-orders.png"),
        ("13700000001", 0, "05-rider-hall.png"),
        ("13700000001", 1, "06-rider-tasks.png"),
        ("13600000001", 0, "07-admin-dashboard.png"),
        ("13600000001", 2, "08-admin-refunds.png"),
    )
    for phone, tab_index, name in shots:
        session = app.ctx.auth.login(phone, app.ctx.settings.demo_code)
        app.on_login(session)
        refund = ensure_pending_refund(app) if name.startswith("08-") else None
        app.current_view.refresh()
        app.current_view.notebook.select(tab_index)
        snap(app, name)
        dismiss_refund(app, refund)
        app.show_login()
        app.update()

    app.destroy()


if __name__ == "__main__":
    main()
