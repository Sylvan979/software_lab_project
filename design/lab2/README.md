# 实验二设计资料

本目录保存实验二（需求分析与 UML 建模）的交付内容，是实验三实现的直接依据。

```text
design/lab2/
├── uml/                  # 7 张 UML 图（PlantUML 源文件 + PNG）
│   ├── UML用例图.puml / .png
│   ├── UML类图.puml / .png
│   ├── UML时序图.puml / .png
│   ├── UML活动图.puml / .png
│   ├── UML状态图.puml / .png
│   ├── UML组件图.puml / .png
│   └── UML部署图.puml / .png
├── ui/                   # 12 张界面设计稿
└── 实验2_设计报告.pdf     # 设计报告
```

UML 图由 PlantUML 渲染，`.puml` 为可编辑源文件；界面设计稿对应登录、顾客点餐、下单支付、配送追踪、退款、商家工作台、菜品库存、骑手抢单、运营看板与审核日志等场景。

实验三的实现与这些设计元素的对应关系见仓库根目录的 `docs/design-mapping.md`。
