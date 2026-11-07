# 城市外卖点餐与配送平台（软件工程实验一 ~ 三）

本仓库保存课程三次实验的全部交付物：

| 目录 | 内容 |
| --- | --- |
| `lab1/` | 实验一：需求访谈记录、需求规格说明书、报告与提交包 |
| `design/lab2/` | 实验二：7 张 UML 图、12 张界面设计稿、设计报告 |
| 仓库根目录 | 实验三：依据实验二设计实现的可运行原型（`app/`、`tests/`、`run.py`） |

实验三是顾客、商家、骑手、平台管理员四端合一的桌面应用。

- 语言与运行时：Python 3.11+（开发环境 3.14）
- 图形界面：Tkinter（标准库，无需安装第三方依赖）
- 数据存储：JSON 文件（`data/platform.json`），原子写入，模拟数据库
- 测试：`python -m unittest discover -s tests -v`

## 实验二设计资料

`design/lab2/` 保存实验二（UML 建模与界面原型）的交付物：7 张 UML 图（`.puml` 源文件与 `.png`）、12 张界面设计稿和设计报告 PDF，详见 [design/lab2/README.md](design/lab2/README.md)。

## 快速开始

```powershell
python run.py            # 启动图形界面
python -m app.cli seed   # 生成演示数据（首次运行自动执行）
python -m app.cli demo   # 命令行跑通完整业务流程
python -m unittest discover -s tests -v
python -m pylint app     # 代码规范检查
```

开发环境：Python 3.14.7；运行仅需标准库，pylint 只用于开发期检查。

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

## 工程化记录

| 分支 | 内容 |
| --- | --- |
| `feat/domain-model` | 领域模型、枚举、状态机、计价 |
| `feat/persistence` | JSON 数据库、通用仓储、编解码 |
| `feat/services` | 业务服务、异常体系、依赖装配、演示数据、命令行 |
| `feat/jobs` | 超时兜底定时任务与测试 |
| `feat/ui` | 登录与四端 Tkinter 界面 |
| `chore/code-quality` | pylint 清理、共用消息面板 |
| `fix/demo-repeatability` | 演示脚本可重复执行 |
| `docs/engineering` | 设计映射、AI 使用记录、测试记录 |
| `fix/refund-delivery-consistency` | 退款后关闭配送单 |
| `fix/storage-retry` | Windows 原子替换重试 |
| `chore/report-artifacts` | 报告截图与验证记录 |
| `docs/lab3-report` | 实验报告源文件与 PDF |

每个分支完成后通过 `git merge --no-ff` 合入 `main`；生成提交使用 `[AI 生成]`，人工修正使用 `[人工修改]`。

报告与提交包：

```powershell
powershell -File report\render-report.ps1    # 由 report.md 渲染 PDF
powershell -File tools\package_submission.ps1 # 生成实验3_241220075_赵力丹.zip
```

远程仓库（需在具备权限的环境中执行，仓库中不保存任何令牌）：

```powershell
git remote add origin https://github.com/<用户名>/<仓库名>.git
git push -u origin main
git push origin --all
```

## 文档

- [设计映射](docs/design-mapping.md)：UML 元素到代码、状态机、持久化与规模统计
- [AI 使用记录](docs/ai-usage.md)：协作流程、生成内容、异常输出处理
- [测试记录](docs/testing.md)：编译、测试、pylint、命令行与界面验收
- [界面按钮测试记录](docs/ui-test-record.md)：逐按钮用例、执行结果与缺陷修复
