# WenQu × RepoSocratic

- **应用工程**：[WenQu](https://github.com/fjnuslw/WenQu)
- **模型训练与工具框架**：[RepoSocratic](https://github.com/fjnuslw/RepoSocratic)
- **K2 / RL-73 LoRA**：[Hugging Face](https://huggingface.co/xiongsir1/reposocratic-interviewer)

WenQu 围绕简历、岗位和真实项目组织面试训练；RepoSocratic 培养能够读项目并形成题单的 9B 面试官。两个项目目前独立运行，本次新增文档关联，不改变现有 Provider、会话逻辑或部署方式。

## 已交付的能力

WenQu 提供简历/JD 分析、组卷、Pi Agent 会话、只读仓库工具、语音交互、评分和复习。RepoSocratic 提供自主取证轨迹、27B→9B SFT/KD、在线 GRPO、统一评测实现与两版发布权重。

## 对接方向

首版接入异步“项目备课”服务：WenQu 导入项目与参与背景，RepoSocratic 读取固定快照并返回 `PreparedInterview`，WenQu 按主问题逐题主持面试。模型权重托管页面不是推理 API，常驻服务与快照传输需要后续实现。

| 题单内容 | 可见范围 |
|---|---|
| 主问题 `question` | 当前候选人问题，按原文呈现 |
| `intent`、`basis` | 服务端面试目标与证据 |
| `follow_up` | 回答后按条件选择，不预先暴露 |
| `project_understanding`、`open_points` | 服务端备课与未知事项 |

## 当前代码中的接入点

- [项目准备 API](../apps/api/src/getoffer/api/routers/grill.py)：增加备课任务触发与状态。
- [会话类型](../apps/agents/src/types.ts)和 [HTTP schema](../apps/agents/src/server.ts)：扩展明确的项目题单来源；现有 `bank/resume` 标签不直接复用为模型生成来源。
- [会话控制](../apps/agents/src/session.ts)：把项目题单接入明确的逐题/追问状态机；`mock` 和 `grill` 当前行为不同。
- [项目面试页](../apps/web/src/app/(app)/grilling/page.tsx)：展示备课进度与开始面试入口。

模型侧保留 RepoSocratic 的 `list_tree/search_literal/read_lines` 工具协议与发布采样配置。WenQu 的工具接口及全局模型配置并非即插即用的等价替换。

首个联调验收覆盖项目导入、备课、逐题面试和报告，并检查内部依据不外露、会话隔离与错误观察。完整设计以 [RepoSocratic 对接文档](https://github.com/fjnuslw/RepoSocratic/blob/main/docs/WENQU.md)为准。
