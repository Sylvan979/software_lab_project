"""命令行入口：初始化演示数据、运行一遍完整业务流程。

``python -m app.cli demo`` 不依赖图形界面，便于在无桌面环境中验证服务层。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from app.config import DEFAULT_SETTINGS
from app.container import AppContext, build_context
from app.domain.enums import OrderStatus
from app.domain.models import User
from app.seed import DEMO_CODE, seed_demo_data


def ensure_demo_data(ctx: AppContext) -> dict[str, str]:
    if ctx.repos.users.count() == 0:
        return seed_demo_data(ctx)

    def user(phone: str) -> User:
        found = ctx.repos.users.find_by_phone(phone)
        assert found is not None, f"缺少演示账号 {phone}"
        return found

    customer = user("13800000001")
    customer2 = user("13800000002")
    merchant_a = user("13900000001")
    merchant_b = user("13900000002")
    rider = user("13700000001")
    admin = user("13600000001")
    store_a = ctx.repos.stores.by_merchant(merchant_a.user_id)
    store_b = ctx.repos.stores.by_merchant(merchant_b.user_id)
    assert store_a and store_b
    dishes_a = {d.name: d.dish_id for d in ctx.repos.dishes.by_store(store_a.store_id)}
    dishes_b = {d.name: d.dish_id for d in ctx.repos.dishes.by_store(store_b.store_id)}
    return {
        "admin": admin.user_id,
        "customer": customer.user_id,
        "customer2": customer2.user_id,
        "merchant_a": merchant_a.user_id,
        "merchant_b": merchant_b.user_id,
        "rider": rider.user_id,
        "store_a": store_a.store_id,
        "store_b": store_b.store_id,
        "dish_a_hot": dishes_a["宫保鸡丁"],
        "dish_a_rice": dishes_a["蛋炒饭"],
        "dish_a_drink": dishes_a["冰豆浆"],
        "dish_b_salad": dishes_b["鸡胸沙拉"],
        "dish_b_sandwich": dishes_b["牛油果三明治"],
    }


def _line(title: str) -> None:
    print(f"\n=== {title} ===")


def run_demo(ctx: AppContext) -> int:
    ids = ensure_demo_data(ctx)
    uid = ids["customer"]
    address = ctx.users.default_address(uid)
    assert address is not None

    _line("1. 顾客加购并提交订单（幂等）")
    ctx.cart.clear(uid)
    ctx.cart.add_item(uid, ids["dish_a_hot"], 2)
    ctx.cart.add_item(uid, ids["dish_a_rice"], 1)
    summary = ctx.cart.summary(uid)
    key = f"demo-{datetime.now():%Y%m%d%H%M%S}"
    first = ctx.orders.checkout(uid, address.address_id, remark="少辣", idempotency_key=key)
    repeat = ctx.orders.checkout(uid, address.address_id, remark="少辣", idempotency_key=key)
    print(f"购物车商品金额：{summary.goods_amount} 元")
    print(f"订单号：{first.order.order_id}，应付：{first.order.payable_amount} 元")
    print(f"重复提交返回：{repeat.order.order_id}（reused={repeat.reused}）")
    assert first.order.order_id == repeat.order.order_id

    _line("2. 支付 → 商家接单 → 出餐 → 骑手取送 → 确认收货")
    ctx.orders.pay(first.order.order_id, uid)
    ctx.orders.merchant_accept(first.order.order_id, ids["merchant_a"])
    ctx.orders.mark_ready(first.order.order_id, ids["merchant_a"])
    task = ctx.repos.deliveries.by_order(first.order.order_id)
    assert task is not None
    ctx.delivery.grab(task.task_id, ids["rider"])
    ctx.delivery.pickup(task.task_id, ids["rider"])
    delivered_task = ctx.delivery.deliver(task.task_id, ids["rider"])
    ctx.orders.confirm_receipt(first.order.order_id, uid)
    ctx.orders.review(first.order.order_id, uid, 5, "分量足，送得很快")
    order = ctx.repos.orders.get(first.order.order_id)
    print(
        f"最终状态：{order.status.label}，"
        f"取餐/送达时间：{delivered_task.picked_at is not None}/{delivered_task.delivered_at is not None}"
    )
    assert order.status is OrderStatus.COMPLETED

    _line("3. 退款流程：顾客申请 → 商家同意")
    ctx.cart.clear(uid)
    ctx.cart.add_item(uid, ids["dish_a_hot"], 1)
    second = ctx.orders.checkout(uid, address.address_id).order
    ctx.orders.pay(second.order_id, uid)
    ctx.orders.merchant_accept(second.order_id, ids["merchant_a"])
    ctx.orders.mark_ready(second.order_id, ids["merchant_a"])
    task2 = ctx.repos.deliveries.by_order(second.order_id)
    assert task2 is not None
    ctx.delivery.grab(task2.task_id, ids["rider"])
    ctx.delivery.pickup(task2.task_id, ids["rider"])
    refund = ctx.refunds.apply(second.order_id, uid, "餐品撒漏")
    refund = ctx.refunds.merchant_handle(
        refund.refund_id, ids["merchant_a"], approve=True, comment="抱歉"
    )
    refunded = ctx.repos.orders.get(second.order_id)
    payment = ctx.payments.payment_of(second.order_id)
    print(f"退款单：{refund.refund_id}（{refund.status.label}）")
    print(f"订单状态：{refunded.status.label}，支付流水状态：{payment.status.label if payment else '-'}")
    assert refunded.status is OrderStatus.REFUNDED

    _line("4. 模拟支付失败与库存回滚")
    ctx.cart.clear(uid)
    ctx.cart.add_item(uid, ids["dish_a_drink"], 4)
    drink_before = ctx.repos.dishes.get(ids["dish_a_drink"]).stock
    third = ctx.orders.checkout(uid, address.address_id).order
    ctx.orders.pay(third.order_id, uid, success=False)
    drink_after = ctx.repos.dishes.get(ids["dish_a_drink"]).stock
    cancelled = ctx.repos.orders.get(third.order_id)
    print(f"订单状态：{cancelled.status.label}（{cancelled.cancel_reason}）")
    print(f"库存：{drink_before} → {drink_after}")
    assert cancelled.status is OrderStatus.CANCELLED
    assert drink_before == drink_after

    _line("5. 经营统计")
    stats = ctx.stats.merchant_stats(ids["merchant_a"], day=ctx.stats.today())
    print(
        f"今日订单 {stats.order_count} 笔，完成 {stats.completed_count} 笔，"
        f"营业额 {stats.revenue} 元，退款 {stats.refund_count} 笔，评分 {stats.rating}"
    )
    platform = ctx.stats.platform_stats(ids["admin"])
    print(
        f"平台总订单 {platform.total_orders} 笔，GMV {platform.gmv} 元，"
        f"活跃店铺 {platform.active_stores} 家"
    )
    print("\n演示流程全部通过。")
    return 0


def reset_data() -> None:
    path = DEFAULT_SETTINGS.db_path()
    if path.exists():
        path.unlink()
    print(f"已删除数据文件：{path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="城市外卖平台原型命令行")
    parser.add_argument(
        "command",
        choices=("seed", "demo", "reset", "status"),
        help="seed 初始化数据；demo 跑通完整流程；reset 清空数据；status 查看数据概况",
    )
    args = parser.parse_args(argv)

    if args.command == "reset":
        reset_data()
        return 0

    ctx = build_context()
    if args.command == "seed":
        ids = ensure_demo_data(ctx)
        ctx.db.save()
        print(f"演示数据已就绪：{len(ids)} 个对象，验证码 {DEMO_CODE}")
        return 0
    if args.command == "status":
        print(f"用户 {ctx.repos.users.count()}，店铺 {ctx.repos.stores.count()}，"
              f"订单 {ctx.repos.orders.count()}，退款 {ctx.repos.refunds.count()}")
        for status, count in sorted(ctx.stats.orders_by_status().items()):
            print(f"  {status}: {count}")
        return 0
    return run_demo(ctx)


if __name__ == "__main__":
    sys.exit(main())
