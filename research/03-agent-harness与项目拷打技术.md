# 03 Agent Harness 与"项目拷打"技术调研

> 调研时间：2026-08-28（star/license 经 GitHub API 实时核验）
> 回答：pi agent 是什么？deepseek harness 是什么？如何把完整 repo 喂给 LLM 做深度问答？开源 AI 面试官有哪些可参考？

---

## 0. 结论速览

- "pi agent" = Mario Zechner (badlogic) 的 **pi**（MIT，~17.5k star）：瘦 harness + 少量只读工具 + `.pi/extensions` 扩展机制，哲学是"agent loop 很简单，别用重框架"。
- "deepseek harness" **真实存在** = DeepSeek 官方开源的 **DeepSeek Harness（dsh）**（MIT，~200k star，2026-08-13 发布，"Everything is a Plugin"，Cordis 内核）。
- 代码库理解有四条成熟路线（整仓转文本 / 预生成 wiki / repo map 符号图 / agentic search），本项目应**两段式结合：面试前"备课"用预计算，面试中"查证"用 agentic search**。
- 开源 AI 面试官里最接近"项目拷打"的是 [yizucodes/interview-agent](https://github.com/yizucodes/interview-agent)（无 license，仅借鉴思路）与 [The-Interview-Mentor](https://github.com/ps06756/The-Interview-Mentor)（MIT，阶段机+追问链+rubric）。

## 1. pi agent（badlogic/pi-mono）

- 仓库：[badlogic/pi-mono](https://github.com/badlogic/pi-mono)（主开发迁移至 [earendil-works/pi](https://github.com/earendil-works/pi)）；官网 [pi.dev](https://pi.dev)；作者长文 [What I learned building a minimal coding agent](https://mariozechner.at/posts/2025-11-30-pi-coding-agent/)（2025-11-30）；第三方解读 [developersdigest](https://www.developersdigest.tech/blog/pi-deep-dive-agent-toolkit-architecture)。
- 定位："There are many agent harnesses but this one is yours."——极简 agent harness，MIT，TypeScript monorepo。
- 核心包：`pi-coding-agent`（CLI）、`pi-agent-core`（agent 运行时：tool calling + 状态管理）、`pi-ai`（统一多 provider LLM API：OpenAI/Anthropic/Google 等，模型目录来自 models.dev）、`pi-tui`（终端 UI）、`pi-telemetry`。
- 架构要点：
  1. **Harness 主循环极简**：system prompt + LLM + 工具的事件驱动循环（tool call → 执行 → 回填 → 直到 turn 结束）。作者强调"构建 agent loop 是 trivial 的"，agent 应可被人随时插入接管（steerable），而非全自动。
  2. **工具系统**：内置工具极少（read/bash/edit/write 一类），工具=带参数 schema 的异步函数；**不做 RAG、不做代码库索引**，靠 agentic search（读文件+grep/find）。
  3. **扩展机制（最有特色）**：扩展是放进 `.pi/extensions` 的 TypeScript 文件，可 hook agent 事件、注册自定义工具、定制 prompt/会话行为——"用扩展把通用 harness 改造成领域专用 agent"。
  4. **会话**：JSONL 追加式文件，可重放/分析/导出 HTML。
  5. 安全：不内置权限系统，官方给容器化/沙箱方案。
- **对本项目的借鉴**：面试官 agent 不需要 coding agent 的全量工具，只要 `read_file / grep / list_dir / get_repo_map / get_resume_claim` 等只读工具 + "出题-追问-评分"策略层；pi-agent-core 循环可直接复用（MIT）或仿写；"persona/追问策略/评分 rubric 做成可插拔扩展"正是 pi 的哲学；JSONL 会话日志天然适合面试回放与复盘。

## 2. DeepSeek Harness（deepseek-ai/deepseek-harness）

- **确认存在**：DeepSeek 官方 agent harness，2026-08-13 创建，developer preview；口号 "Everything is a Plugin"。
- 仓库：[deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)；发布页 [deepseek.com/harness/en/](https://deepseek.com/harness/en/)；架构文档[中文版](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.zh.md)；~200k star，MIT，TypeScript（pnpm monorepo，含 python 目录）；`npx @deepseek-ai/dsh web` 一键起 Web UI（127.0.0.1:3080）。
- 架构要点：
  1. **Agent = Model + Harness**：模型只是可替换插件，harness 承载全部工程能力。
  2. **Cordis 内核**：插件向共享上下文贡献服务、类型化事件、可逆副作用；九大类能力全部可热插拔（模型适配器/工具注册表/会话日志/技能/沙箱/存储/主循环等）。设计源自《A Programming Paradigm for Spatiotemporal…》论文。
  3. **三种运行模式**：Standard（全插件）；**Code Mode SDK**（模型生成 TypeScript 代码编排工具调用，替代逐次 function-calling）；**Minimal**（只留 bash + str_replace_editor 两个工具，与 pi/Claude Code 的"少工具+agentic search"路线一致）。
  4. `dsh-core`：harness 内核 + agent 编排 + 插件加载器 + 运行时状态 + **append-only 会话日志**；Web UI 有 Trajectory view。
  5. 技能/约定文件：`AGENTS.md`、`dsh skill`、`dsh review`、`dsh checklist` 等。
- 配套：[awesome-deepseek-agent](https://github.com/deepseek-ai/awesome-deepseek-agent)（官方指南集）；社区解读：[知乎](https://zhuanlan.zhihu.com/)《DeepSeek Harness 实现原理》、tonybai.com、[developersdigest 45 万行代码解读](https://www.developersdigest.tech)、[MindStudio](https://www.mindstudio.ai/blog/deepseek-harness-agentic-coding)。
- **对本项目的借鉴**：把"面试官"拆成插件（persona/题库/追问策略/评分器/报告生成器各自为插件）；append-only 日志 + trajectory 视图用于面试回放审计；**Minimal 模式启发：拷打 agent 工具面要窄（只读代码+简历证据检索），防止"看答案作弊"**；dsh review/checklist 类比"面试评估 checklist"。注意 dsh 刚发布、API 变动快、为 coding 场景设计——**作为架构思想参考，不直接依赖**。

## 3. 代码库理解 / 摄入的四种路线

### 3.1 整仓转文本：gitingest / Repomix
- [gitingest](https://github.com/coderamp-labs/gitingest)（15,357 star，MIT，Python；[gitingest.com](https://gitingest.com/)）：遍历仓库→默认排除噪声（lock/二进制/node_modules）→输出"目录树+各文件内容"单文件 digest + token 估算；有 MCP server。
- [Repomix](https://github.com/yamadashy/repomix)（28,094 star，MIT，TS）：同类，XML/Markdown 输出、token 计数、远程仓库支持。
- 角色：**小中型仓库兜底**；大仓库爆 token，需 3.2–3.4。

### 3.2 预生成结构化知识：DeepWiki 路线
- [DeepWiki](https://deepwiki.com/)（Cognition，Devin 驱动）：repo→自动生成含 Mermaid 架构图/数据流/组件关系的 wiki，**每条结论链接回源码位置**；[发布博客](https://cognition.com/blog/deepwiki)。
- 开源克隆 [deepwiki-open](https://github.com/AsyncFuncAI/deepwiki-open)（17,808 star，MIT，Python）：完整可复用管线 **clone→代码分块→embedding→RAG→LLM 生成 wiki+Mermaid 图**，多 provider。
- 角色：**面试前"备课"**——为被拷打项目自动生成架构 wiki，追问时引用具体文件。

### 3.3 符号图 + repo map：aider 路线
- [aider repo map](https://aider.chat/2023/10/22/repomap.html)（[aider](https://github.com/Aider-AI/aider) 48,546 star，Apache-2.0）：tree-sitter 解析每文件提取**定义与引用**→构建多重有向图（节点=文件，边=符号引用，权重=引用次数）→**personalized PageRank** 排序→按 token 预算二分截断渲染"最重要文件+关键符号签名"。1k token 的 repo map 使代码编辑基准提升约 6 倍。抽象描述见 [agentpatterns.ai](https://agentpatterns.ai/context-engineering/repository-map-pattern/)。
- 角色：**出题权重**——被最多模块依赖的符号/文件就是"项目灵魂"，正是最该拷打的地方。

### 3.4 代码 RAG 分块与图索引
- **cAST**（[arXiv 2506.15655](https://arxiv.org/html/2506.15655v1)）：tree-sitter AST 递归 split-then-merge——超大节点切开、过小兄弟节点合并，保证 chunk 落在语法子树边界（完整函数/类）；RepoBench 检索 Recall 与 SWE-bench 生成指标优于按行切分。
- 符号索引+import/call graph：共识是"AST chunk 向量检索作种子 + 沿 import/调用图扩展邻居符号"（[综述](https://arxiv.org/html/2510.04905v1)）。
- chunk 元数据建议：文件路径、所属类、imports、被引用关系、**git 最近改动者/时间（用于"这段代码是不是候选人写的"归属判断）**。

### 3.5 Anthropic 官方：Claude Code 怎么理解代码库
- [官方博客](https://claude.com/blog/how-claude-code-works-in-large-codebases-best-practices-and-where-to-start)（2026-05-14）：**agentic search 路线（不做向量索引）**——像工程师一样遍历文件系统、grep 精确定位、顺引用跳转；不用向量索引的原因：索引过期（stale index）、agentic search 永远读最新代码。
- Harness 五大扩展点：CLAUDE.md、hooks、skills、plugins、MCP servers；subagent 分工（只读 subagent 勘探绘图，主 agent 编辑）。
- 方法论：[Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)。

### 3.6 四路线小结（决定 F4 的两段式架构）

| 路线 | 代表 | 优点 | 缺点 | 在本项目中的角色 |
|---|---|---|---|---|
| 整仓转文本 | gitingest / Repomix（MIT） | 简单无损 | 大仓库爆 token | 小项目兜底 / 预处理输入 |
| 预生成结构化知识 | deepwiki-open（MIT） | 架构级理解、带源码引用、可对话 | 需提前生成、可能过期 | 面试前"备课" |
| 符号图+repo map | aider repomap（Apache-2.0）、cAST | 精准、可控 token、可算考点权重 | 工程复杂度较高 | 出题权重+上下文压缩 |
| agentic search | Claude Code、pi、dsh Minimal | 永远最新、无需索引 | 慢、多轮工具成本 | 面试中"现场查证" |

## 4. 开源 AI 面试官项目盘点

| 项目 | Star | License | 形态 | 关键架构点 |
|---|---|---|---|---|
| [Snailclimb/interview-guide](https://github.com/Snailclimb/interview-guide)（JavaGuide 作者） | 3,117 | **AGPL-3.0（传染，勿抄代码）** | Java 全栈平台 | Spring Boot+Spring AI+React+PostgreSQL/pgvector+Redis；简历分析、模拟面试（文字+语音）、题库面试、知识库 RAG |
| [AsyncFuncAI/deepwiki-open](https://github.com/AsyncFuncAI/deepwiki-open) | 17,808 | MIT | repo wiki 生成器 | 非面试项目，但是"repo 理解"最佳开源参照 |
| [jennifer88huang/interview-skills](https://github.com/jennifer88huang/interview-skills) | 316 | 无 license（仅借鉴 prompt 思路） | Claude Code Skill | **JD+简历双输入**：匹配度分析、识别薄弱点、10 道题含难度与**追问链**、HR 面谈薪 |
| [ps06756/The-Interview-Mentor](https://github.com/ps06756/The-Interview-Mentor) | 98 | MIT | ~40 个面试官 skill | **面试阶段机（opening→main→follow-ups→closing）**、4 级提示系统、每技能带题库与评估 rubric |
| [FoloUp/FoloUp](https://github.com/FoloUp/FoloUp) | 1,251 | MIT | 企业侧 AI 语音面试 | 上传简历→LLM 即时生成定制题→语音面试 |
| [IliaLarchenko/Interviewer](https://github.com/IliaLarchenko/Interviewer) | 125 | Apache-2.0 | 求职者练习 mock | 编码题为主 |
| [yizucodes/interview-agent](https://github.com/yizucodes/interview-agent) | 11 | **无 license（只借鉴思路）** | **语音"项目拷打"（与需求最接近）** | LiveKit 实时语音+GPT-4o-mini+AssemblyAI STT+Cartesia TTS+**ChromaDB 对项目文档 RAG**→上下文感知提问+追问+结构化反馈 |
| [ngoanpv/DeepInterview](https://github.com/ngoanpv/DeepInterview) | — | 开源 | 语音优先多语言 mock | CV+JD 上传、自适应追问 |
| [alexeygrigorev/ai-engineering-field-guide](https://github.com/alexeygrigorev/ai-engineering-field-guide/blob/main/interview/questions/03-project-deep-dive.md) | — | 开源 | 项目深挖问题清单 | "你解决什么业务问题/真实角色"等问题模板 |

规律：① 驱动模式三分天下——题库驱动（InterviewGuide）、JD+简历驱动（interview-skills/FoloUp）、**项目/repo 驱动（yizucodes，最稀缺也最接近需求）**；② 追问策略参考：interview-skills 追问链 + Interview-Mentor 阶段机/4 级提示 + yizucodes RAG 上下文追问；③ 语音标配：LiveKit Agents SDK（Apache-2.0）或 Vapi + STT/TTS；④ license 风险：AGPL 只可参考设计，无 license 项目不可复制代码。

## 5. 综合："项目拷打 agent"推荐架构（F4 的蓝本）

```
┌──────────── 离线"备课"流水线（每 repo 一次，可缓存） ────────────┐
│ ①repo 摄入: git clone → 噪声过滤（gitingest/Repomix 思路）        │
│ ②结构理解: tree-sitter AST → 符号索引 → aider 式 repo map         │
│    （PageRank=考点权重）+ import/call graph                       │
│    + git 归属分析（git log --author → 哪些代码是候选人写的）       │
│ ③语义层: cAST 式 AST 分块 → embedding → 向量库(pgvector/Chroma)   │
│    + LLM 层级摘要（文件→模块→全仓）生成架构 wiki（deepwiki-open 式）│
└──────────────────────────────────────────────────────────────┘
┌──────────── 简历对齐（每次上传一次） ──────────────────────────┐
│ ④简历解析 → 抽取"声明"（项目/技术栈/量化指标/角色）→ 与 repo 证据 │
│    映射：声明有但代码无 / 技术词无对应实现 / 指标无法验证         │
│    → 注水疑点清单                                                │
└──────────────────────────────────────────────────────────────┘
┌──────────── 在线"拷打"Agent 循环（pi/dsh 式瘦 harness） ────────┐
│ ⑤问题生成: 蓝图 = repo map 权重 × JD 相关度 × 简历声明覆盖度      │
│    × 注水疑点；题型：设计决策题/细节题/权衡题/故障排查题           │
│ ⑥拷打循环: 事件驱动主循环 + 窄只读工具面                          │
│    （read_file/grep/list_dir/get_repo_map/get_resume_claim）      │
│    追问策略 = 阶段机 + 每题追问链(3~4层) + 4级提示降级             │
│    + "回答 vs 代码证据"实时比对 + 自适应难度升降                   │
│ ⑦评分报告: 多维 rubric（理解深度/设计决策质量/代码归属证据/表达/   │
│    诚实度）→ 证据链报告（每条结论引用 文件:行号）+ 薄弱点清单       │
│    + trajectory 回放 + 复习计划                                   │
└──────────────────────────────────────────────────────────────┘
```

**关键设计决策**：
1. harness 选 **pi 式瘦循环**（几百行主循环+窄只读工具+extension 插槽）；dsh 的"插件贡献服务/事件"作为代码组织思想而非直接依赖。
2. **两段式代码理解**：预计算 wiki/repo map/向量索引保证面试不冷场；agentic search 保证"临场质证"准确（Anthropic 立场：活跃代码库不做易过期向量索引，索引只作加速缓存）。
3. **注水识别是差异化卖点**：git log --author + 代码复杂度 + 测试覆盖 + 声明-证据映射→疑点清单喂给追问策略；报告每个评分点附文件：行号级证据链。
4. 合规：候选人上传的第三方仓库只做分析，注意版权与保密条款。

## 6. 可复用组件与 license 速查

| 环节 | 组件 | License | 用法 |
|---|---|---|---|
| Agent 主循环 | [pi-mono](https://github.com/badlogic/pi-mono) 的 pi-agent-core / pi-ai | MIT | 复用运行时+多 provider 层，或仿写 |
| 架构参照 | [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) | MIT | 学插件化与会话日志，MIT 可安全移植 |
| repo→文本 | [repomix](https://github.com/yamadashy/repomix) / [gitingest](https://github.com/coderamp-labs/gitingest) | MIT | 小仓库整仓兜底 |
| 代码地图 | aider `repomap.py` 思路 + tree-sitter | Apache-2.0 | PageRank 出题权重 |
| AST 分块 | cAST 算法（[arXiv](https://arxiv.org/html/2506.15655v1)）+ tree-sitter | 论文/MIT | 向量索引切分器 |
| repo wiki | [deepwiki-open](https://github.com/AsyncFuncAI/deepwiki-open) | MIT | 二开：自动"备课" |
| 面试流程/prompt | [The-Interview-Mentor](https://github.com/ps06756/The-Interview-Mentor)（阶段机+4级提示+rubric）、interview-skills（追问链，无 license 仅借鉴思想） | MIT / 无 | skill/prompt 模板基底 |
| 语音面试 | [FoloUp](https://github.com/FoloUp/FoloUp) + LiveKit Agents SDK | MIT / Apache-2.0 | 需要语音拷打时 |
| 向量库 | ChromaDB / pgvector | Apache-2.0 / PostgreSQL License | 语义层 |
| 反面教材 | [Snailclimb/interview-guide](https://github.com/Snailclimb/interview-guide) | **AGPL-3.0** | 闭源平台只可参考设计，不可复制代码 |

## 7. 演进路线建议

MVP（纯文字：repo 摄入 + repo map + 瘦循环 + 追问链 + rubric 报告）→ 二期（deepwiki 式 wiki + LiveKit 语音）→ 三期（dsh 式插件化岗位包 + trajectory 复盘产品化）。

## 主要来源

- pi：[badlogic/pi-mono](https://github.com/badlogic/pi-mono)、[pi.dev](https://pi.dev/)、[作者博客](https://mariozechner.at/posts/2025-11-30-pi-coding-agent/)、[developersdigest 解读](https://www.developersdigest.tech/blog/pi-deep-dive-agent-toolkit-architecture)、[earendil-works/pi](https://github.com/earendil-works/pi)
- DeepSeek Harness：[deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)、[发布页](https://deepseek.com/harness/en/)、[架构文档(中文)](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.zh.md)、[MindStudio](https://www.mindstudio.ai/blog/deepseek-harness-agentic-coding)、[awesome-deepseek-agent](https://github.com/deepseek-ai/awesome-deepseek-agent)
- 整仓转文本：[gitingest](https://gitingest.com/)、[repomix](https://github.com/yamadashy/repomix)、[openreplay 对比](https://blog.openreplay.com/git-repos-llm-ready-text/)
- DeepWiki：[deepwiki.com](https://deepwiki.com/)、[Cognition 博客](https://cognition.com/blog/deepwiki)、[deepwiki-open](https://github.com/AsyncFuncAI/deepwiki-open)
- aider repo map：[博客](https://aider.chat/2023/10/22/repomap.html)、[文档](https://aider.chat/docs/repomap.html)、[agentpatterns](https://agentpatterns.ai/context-engineering/repository-map-pattern/)
- 代码 RAG：[cAST 论文](https://arxiv.org/html/2506.15655v1)、[代码检索综述](https://arxiv.org/html/2510.04905v1)
- Claude Code：[官方博客](https://claude.com/blog/how-claude-code-works-in-large-codebases-best-practices-and-where-to-start)、[Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
- 开源面试官：[interview-guide](https://github.com/Snailclimb/interview-guide)、[interview-skills](https://github.com/jennifer88huang/interview-skills)、[The-Interview-Mentor](https://github.com/ps06756/The-Interview-Mentor)、[FoloUp](https://github.com/FoloUp/FoloUp)、[Interviewer](https://github.com/IliaLarchenko/Interviewer)、[interview-agent](https://github.com/yizucodes/interview-agent)、[DeepInterview](https://github.com/ngoanpv/DeepInterview)、[ai-interviewer topic](https://github.com/topics/ai-interviewer)
