# PreCex

Counterexample-driven Pre-synthesis RTL Bug Localization and Repair Agent.

研究项目：反例驱动的综合前 RTL 缺陷定位与修复智能体。

## 文档

- [项目方案](docs/项目方案.md)
- [详细方案说明](docs/详细方案说明.md)
- [难度评估](docs/难度评估.md)
- [文献调研与评估](docs/文献调研与评估.md)

## 目录结构

```
precex/
├── docs/      # 方案文档
├── rtl/       # 黄金 RTL 模块
├── samples/   # BugBench-PS 数据集（L3 样本，7 件套）
├── harness/   # 评测管线
├── scripts/   # 工具脚本（注入器/解析器）
└── smoke/     # 工具链冒烟测试（Gate-1）
```
