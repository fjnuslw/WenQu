# 改进型 Spec 索引

本目录存放在主产品 Spec 已经确定之后，对某个模块进行质量、架构或交互升级的独立规范。

主 Spec `docs/spec.md` 继续回答“产品要有什么”；本目录回答“现有实现哪里需要升级、为什么升级、边界如何保持、怎样证明升级有效”。这里不是开发日志，也不以代码已经存在作为验收依据。

## 文档约定

- 编号：`IMP-<模块>-<序号>`，例如 `IMP-F3-001`。
- 一份文档只处理一个主要问题，跨模块影响必须显式列出。
- 状态流转：`Proposed → Accepted → Implementing → Verified → Superseded`。
- `Accepted` 后才构成对父 Spec 对应小节的补充；发生冲突时，在改进 Spec 中逐条声明覆盖关系。
- 每份 Spec 至少包含：现状证据、目标与非目标、职责边界、协议、失败策略、迁移方案、验收标准。
- 模型 Prompt、运行时状态、外部 API 和离线评价必须分层描述，避免把实现细节误做成模型协议。

## 当前条目

| 编号 | 模块 | 标题 | 状态 |
|---|---|---|---|
| [IMP-F3-001](./IMP-F3-001-interview-orchestration-v2.md) | F3 模拟面试 | 最小决策协议与 Harness 编排 v2 | Verified |
| [IMP-F3-002](./IMP-F3-002-grounded-chinese-interview-and-voice.md) | F3 模拟面试 | 中文面试、简历证据化深挖与可替换语音输出 | Implementing |
| [IMP-G1-001](./IMP-G1-001-repository-intelligence-v2.md) | G1 项目拷打 | Tree-sitter repo map、pgvector 语义检索与 Git 归属 | Implementing（仅 Provider 验收门） |
