"""演示数据：四类账号、两家店铺与菜单。

所有数据都通过服务层创建，等价于人工在界面上的操作；
重复启动不会重复插入（按手机号与店铺名判断）。
"""

from __future__ import annotations

from decimal import Decimal

from app.container import AppContext
from app.domain.enums import UserRole
from app.services.privacy import is_valid_phone

DEMO_CODE = "123456"

DEMO_ACCOUNTS = (
    ("13800000001", "陈晓", UserRole.CUSTOMER),
    ("13800000002", "李萌", UserRole.CUSTOMER),
    ("13900000001", "张建国", UserRole.MERCHANT),
    ("13900000002", "林小满", UserRole.MERCHANT),
    ("13700000001", "王峰", UserRole.RIDER),
    ("13700000002", "赵磊", UserRole.RIDER),
)


def seed_if_empty(ctx: AppContext) -> bool:
    if ctx.repos.users.count() > 0:
        return False
    seed_demo_data(ctx)
    return True


def seed_demo_data(ctx: AppContext) -> dict[str, str]:
    """创建演示数据并返回常用主键，便于命令行演示与测试。"""
    auth, users, stores = ctx.auth, ctx.users, ctx.stores

    # 管理员账号由系统预置，不开放自助注册（REQ-001）
    from app.domain.models import Admin

    admin = Admin(user_id=ctx.db.next_id("USR"), phone="13600000001", nickname="平台管理员")
    ctx.repos.users.add(admin)

    customers = {}
    for phone, nickname, role in DEMO_ACCOUNTS:
        if not is_valid_phone(phone):
            continue
        user = auth.register(phone, nickname, role, DEMO_CODE)
        customers[phone] = user

    customer = customers["13800000001"]
    users.add_address(
        customer.user_id,
        receiver="陈晓",
        phone="13800000001",
        detail="幸福小区 3 栋 502",
        x_km=0.6,
        y_km=1.0,
        set_default=True,
    )
    second = customers["13800000002"]
    users.add_address(
        second.user_id,
        receiver="李萌",
        phone="13800000002",
        detail="阳光花园 8 栋 1102",
        x_km=2.0,
        y_km=1.8,
        set_default=True,
    )

    merchant_a = customers["13900000001"]
    store_a = stores.apply_store(
        merchant_a.user_id,
        name="川味小厨",
        description="现炒川菜，午餐高峰提前下单",
        address_text="学府路 18 号 1 层",
        x_km=0.0,
        y_km=0.0,
        min_order_amount=Decimal("15.00"),
    )
    stores.approve_store(admin.user_id, store_a.store_id)
    stores.set_business_status(merchant_a.user_id, True)
    hot = stores.add_category(merchant_a.user_id, "热菜", 1)
    staple = stores.add_category(merchant_a.user_id, "主食", 2)
    drinks = stores.add_category(merchant_a.user_id, "饮料", 3)
    dishes_a = {
        "宫保鸡丁": stores.add_dish(
            merchant_a.user_id,
            category_id=hot.category_id,
            name="宫保鸡丁",
            price=Decimal("26.00"),
            stock=30,
            description="鸡腿肉、花生米，中辣",
        ),
        "麻婆豆腐": stores.add_dish(
            merchant_a.user_id,
            category_id=hot.category_id,
            name="麻婆豆腐",
            price=Decimal("18.00"),
            stock=40,
            description="嫩豆腐，微辣",
        ),
        "蛋炒饭": stores.add_dish(
            merchant_a.user_id,
            category_id=staple.category_id,
            name="蛋炒饭",
            price=Decimal("14.00"),
            stock=50,
        ),
        "冰豆浆": stores.add_dish(
            merchant_a.user_id,
            category_id=drinks.category_id,
            name="冰豆浆",
            price=Decimal("5.00"),
            stock=100,
        ),
    }

    merchant_b = customers["13900000002"]
    store_b = stores.apply_store(
        merchant_b.user_id,
        name="轻食日记",
        description="低卡沙拉与现烤三明治",
        address_text="图书馆东侧 6 号",
        x_km=1.0,
        y_km=0.5,
        min_order_amount=Decimal("20.00"),
    )
    stores.approve_store(admin.user_id, store_b.store_id)
    stores.set_business_status(merchant_b.user_id, True)
    salad = stores.add_category(merchant_b.user_id, "沙拉", 1)
    sandwich = stores.add_category(merchant_b.user_id, "三明治", 2)
    dishes_b = {
        "鸡胸沙拉": stores.add_dish(
            merchant_b.user_id,
            category_id=salad.category_id,
            name="鸡胸沙拉",
            price=Decimal("28.00"),
            stock=20,
        ),
        "牛油果三明治": stores.add_dish(
            merchant_b.user_id,
            category_id=sandwich.category_id,
            name="牛油果三明治",
            price=Decimal("22.00"),
            stock=25,
        ),
    }

    rider = customers["13700000001"]
    ctx.delivery.set_online(rider.user_id, True)

    return {
        "admin": admin.user_id,
        "customer": customer.user_id,
        "customer2": second.user_id,
        "merchant_a": merchant_a.user_id,
        "merchant_b": merchant_b.user_id,
        "rider": rider.user_id,
        "store_a": store_a.store_id,
        "store_b": store_b.store_id,
        "dish_a_hot": dishes_a["宫保鸡丁"].dish_id,
        "dish_a_rice": dishes_a["蛋炒饭"].dish_id,
        "dish_a_drink": dishes_a["冰豆浆"].dish_id,
        "dish_b_salad": dishes_b["鸡胸沙拉"].dish_id,
        "dish_b_sandwich": dishes_b["牛油果三明治"].dish_id,
    }
