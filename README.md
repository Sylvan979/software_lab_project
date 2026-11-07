# 城市外卖点餐与配送平台

Python + Tkinter 桌面应用，实现顾客点餐、商家接单、骑手配送、平台管理的完整闭环，数据存于本地 JSON。

```
lab1/            需求分析：访谈记录与需求规格
design/lab2/     设计：7 张 UML 图（.puml + .png）、12 张界面设计稿
app/             代码：ui → services → repository → domain
tests/           测试：107 个用例
run.py           入口
```

- 运行：`python run.py`（Python 3.11+，无第三方依赖）
- 测试：`python -m unittest discover -s tests -v`
- 验证码统一 `123456`，演示手机号见 `app/seed.py`
