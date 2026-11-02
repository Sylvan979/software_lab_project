# 城市外卖点餐与配送平台（软件工程实验三）

依据实验二的领域模型与分层组件图实现的可运行原型：顾客、商家、骑手、平台管理员四端合一的桌面应用。

- 语言与运行时：Python 3.11+（开发环境 3.14）
- 图形界面：Tkinter（标准库，无需安装第三方依赖）
- 数据存储：JSON 文件（`data/platform.json`），原子写入，模拟数据库
- 测试：`python -m unittest discover -s tests -v`

## 快速开始

```powershell
python run.py            # 启动图形界面
python -m app.cli seed   # 生成演示数据（首次运行自动执行）
python -m unittest discover -s tests -v
```

演示账号（验证码统一为 `123456`）：

| 角色 | 手机号 | 说明 |
| --- | --- | --- |
| 顾客 | 13800000001 | 陈晓，有收货地址 |
| 商家 | 13900000001 | 川味小厨店主 |
| 商家 | 13900000002 | 轻食日记店主 |
| 骑手 | 13700000001 | 王峰，在线 |
| 管理员 | 13600000001 | 平台管理员 |

## 目录结构

```
app/
├── config.py          全局配置（超时时限、计费规则、路径）
├── exceptions.py      领域异常体系
├── container.py       依赖装配（仓储 → 服务）
├── seed.py            演示数据
├── domain/            领域模型、枚举、状态机、计价
├── repository/        JSON 数据库、通用仓储、编解码
├── services/          业务服务（对应用户/商家/订单/配送/退款等模块）
├── jobs/              定时任务（超时兜底）
└── ui/                Tkinter 界面（登录 + 四端）
tests/                 单元测试与流程测试
docs/                  设计与实现映射、工程过程记录
run.py                 程序入口
```

## 架构约定

- 分层单向依赖：`ui → services → repository → domain`，`jobs` 只调用服务。
- 领域对象不访问数据库，服务负责鉴权、事务边界与状态迁移，仓储只负责持久化。
- 订单状态只能经 `OrderStateMachine` 迁移，非法迁移抛出 `InvalidTransitionError`。
- 金额一律使用 `Decimal`，对外保留两位小数。
- 所有关键操作写入审计日志（REQ-014），日志只追加。
