# 城市外卖点餐与配送平台

一个用 Python + Tkinter 写的桌面小项目，实现顾客点餐、商家接单、骑手配送、平台管理的完整闭环，数据存在本地 JSON 文件里。

- 运行：`python run.py`（需要 Python 3.11+，无第三方依赖）
- 测试：`python -m unittest discover -s tests -v`
- 演示账号密码验证码统一为 `123456`，手机号见 `app/seed.py`

代码分层：`ui → services → repository → domain`。
