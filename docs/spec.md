# 问渠 WenQu（工作名 get_offer）— 大模型应用/Agent 开发求职平台 · 产品与技术 Spec

| 项 | 值 |
|---|---|
| 版本 | v0.3（K1 知识冷启动完成态） |
| 日期 | 2026-08-29 |
| 状态 | **K1 已完成 + I1 闭环打通**：题库 2 万+（track/厂商/标签三维组织）、组卷→题单驱动面试→评分报告端到端实测；I1 剩余：简历押题/报告页/失分点回流 |
| 配套调研 | [research/01-竞品调研](../research/01-竞品调研.md) · [02-数据渠道](../research/02-开源面经题库与数据渠道.md) · [03-harness技术](../research/03-agent-harness与项目拷打技术.md) · [04-简历画像](../research/04-简历画像与考点映射.md) · [05-功能补充](../research/05-功能补充与差异化结论.md) |

**决策记录**：

| # | 决策 | 取值 | 状态 |
|---|---|---|---|
| D1 | 产品定位 | **完整产品一次架构到位**，按垂直切片交付（非 MVP 堆叠） | 用户已确认（2026-08-28） |
| D2 | 数据获取 | 合规优先：开源仓库 + 牛客/linux.do 公开内容 + 人工摘录；小红书/抖音禁止程序化爬取 | 已确认 |
| D3 | 模型接入 | OpenAI 兼容协议；agent 运行时直接依赖 pi-ai（原生 deepseek/moonshot/qwen provider），DeepSeek 主力。**模型 id 以 API 实测为准（已实测小写）：`deepseek-v4-flash-vision-exp`**（实验模型经 createProvider 显式注册进 pi 目录） | 已确认 |
| D4 | 交付顺序 | 知识先行（题库/面经是模拟面试与拷打的弹药），但架构从第一天就是完整形态 | 已确认 |
| D5 | 工程原则 | 禁止正则硬编码与 fallback 堆砌：结构化解析器 + 类型化错误 + 显式失败（见 §7） | 用户已确认 |
| D6 | WebUI | 高端设计体系，参考 Linear/Vercel/shadcn 等优秀案例（见 §6） | 用户已确认 |
| D7 | 源码复用 | 调研到的源码最大化学习/移植/直接依赖（见 §8 与 `references/` 目录） | 用户已确认 |

---

## 1. 背景与定位

求职大模型应用/Agent 岗，需要一套系统完成 **知识沉淀与检索（面经/题库）→ 对抗式练习（模拟面试）→ 真实项目深度检验（读码拷打）**。三路调研（research/01–03）确立的三个市场空白：读码拷打无产品、垂直按厂商题库缺位、全链路一体化空白。本平台按完整产品推进，同时它本身就是简历上的大模型应用作品集。

## 2. 总体架构

### 2.1 形态：三服务 Monorepo

```
get_offer/
├── apps/
│   ├── web/       Next.js 16 (App Router, TS, Tailwind v4) —— 全部用户界面
│   ├── api/       FastAPI (Python 3.12+) —— 知识工程、检索、复习、评测、简历/仓库分析
│   └── agents/    Node/TS —— 面试与拷打 agent 运行时（直接依赖 @earendil-works/pi-agent-core + pi-ai）
├── references/    调研复用源码（pi-mono、deepwiki-open、gitingest、repomix、The-Interview-Mentor、aider repomap、dsh 架构文档）
├── data/          运行时数据（repo 克隆、session JSONL、导出物），不入库
├── docs/ research/ 文档
└── docker-compose.yml  postgres(pgvector) + meilisearch + redis
```

**为什么是这三个服务**（而非单后端）：
- `agents` 用 TypeScript 是**为了直接复用 pi 生态**（MIT）：agent 循环、工具执行、多 provider、事件流都是久经考验的代码，不重写。pi-ai 原生提供 deepseek/moonshotai/qwen-cn provider（已在 references/pi-mono 源码中核实）。
- `api` 用 Python 是因为知识工程侧的生态（tree-sitter binding、HTTP 解析、embedding、评测）都在 Python；且与 agent 运行时解耦后，LLM 调用策略、评测回归互不干扰。
- 两者只通过 Postgres（状态）与 HTTP/SSE（实时）耦合，各自可独立重启、独立测试。

### 2.2 运行时拓扑

```
                    ┌──────────────────────────── 浏览器 ────────────────────────────┐
                    │  Next.js UI（SSR 页面 + 客户端交互，cmdk 命令面板、TanStack 表格） │
                    └──────────┬──────────────────────────────┬──────────────────────┘
                     REST /api │                       SSE/REST│
                    ┌──────────┴──────────┐        ┌──────────┴─────────────────────┐
                    │  apps/api (FastAPI) │        │  apps/agents (Node, pi 运行时)   │
                    │  ─ 知识工程管道       │        │  ─ F3 面试 agent（状态机+追问）    │
                    │  ─ 题库/面经/检索服务  │        │  ─ F4 拷打 agent（只读工具面）     │
                    │  ─ 简历解析/仓库分析   │        │  ─ 事件流（delta/phase/证据事件）  │
                    │  ─ 复习(SM-2)/评测    │◄──────►│  ─ 会话 JSONL append-only        │
                    │  ─ LLM 网关(结构化输出)│  内部  │                                 │
                    └──┬───────┬───────┬──┘  HTTP └───────────────┬─────────────────┘
                       │       │       │                          │
              ┌────────┴──┐ ┌──┴─────┐ ┌┴────────┐        OpenAI 兼容 API
              │ Postgres  │ │ Meili  │ │ Redis   │       ┌──────────────────┐
              │ + pgvector│ │ (CJK   │ │ (arq    │       │ DeepSeek 主力     │
              │ 结构化+向量 │ │  检索)  │ │  任务队列)│──────►│ GLM/Kimi/Qwen 可切│
              └───────────┘ └────────┘ └─────────┘       │ Ollama 本地      │
                                                          └──────────────────┘
```

### 2.3 核心数据流

| 流 | 路径 |
|---|---|
| 题库导入 | sources 注册表 → git clone（浅）→ markdown AST 解析（mistune）→ LLM 结构化抽取（Pydantic 校验）→ 去重（content-hash/simhash）→ Postgres + Meili 索引 |
| 面经采集 | 牛客 SSR 话题页（selectolax DOM 解析）/ linux.do JSON API / 手动录入 → LLM 抽取为「公司-岗位-轮次-问题树」→ 入库 + 频率统计回写 question_companies |
| 模拟面试 | web → agents `POST /sessions` → 每轮 `POST /sessions/:id/turn`（SSE）→ 状态机选阶段 → pi Agent 生成（事件流）→ JSONL 落盘 → 结束后调 api 评分报告 → 失分点回写复习队列 |
| 项目拷打 | web 上传 repo → api 备课流水线（clone→tree-sitter 符号图→aider 式 repomap PageRank→cAST 分块→pgvector→wiki）+ git 归属分析 + 简历声明-证据映射（疑点清单）→ agents 拷打循环（只读工具现场查证）→ 证据链报告（文件:行号） |
| 学习闭环 | 自测/面试失分 → review_cards（SM-2）→ mastery 图谱 → 今日复习计划；评测：golden_cases 回归 |

## 3. 知识工程：题库丰富度计划（F1/F2 的弹药）

目标不是"有几个仓库导入就完了"，而是**按流水线持续生产**。 richness 目标（Phase K1 出口）：

| 内容 | 目标量 | 来源 |
|---|---|---|
| 知识题（Q&A） | ≥ 3000，去重后 | MIT/Apache 仓库 9 个（底稿）+ 无 license 仓库题干自写（research/02 §5 策略） |
| 真实面经（结构化） | ≥ 500 条 | 牛客话题页 + linux.do 公开帖 + EasyOffer/Junvate + 手动摘录 |
| 手撕专项 | ≥ 50 题（含参考实现与讲解） | 人工编写为主：Attention/RoPE/PPO/多跳检索/Beam Search（论文代码可引用自身） |
| 场景设计题 | ≥ 100 | 按 archetype 生成（RAG 评测体系/多 Agent 审核防串改/权限在召回前执行…）+ 人审 |
| 厂商频率榜 | 8+ 公司 × 12 标签矩阵 | 面经结构化数据挖掘 + UGC 爆料（后期） |
| 衍生内容 | 每题追问链 3–4 层；相似题链接（embedding 近邻） | 自动生成 + 抽检 |

**流水线与解析器政策**（对应 D5）：

| 阶段 | 工具 | 禁止事项 |
|---|---|---|
| 获取 | git（浅克隆）、httpx | — |
| 解析 | markdown→AST 用 mistune v3；HTML→DOM 用 selectolax；Discourse cooked HTML 走 DOM；代码→tree-sitter（Phase K2/G1） | **禁止正则抠 HTML/markdown** |
| 结构化 | LLM 结构化输出 + Pydantic schema 校验 + 单次带错误回传的重试；失败进人审队列 | **禁止 schema 失败后静默丢弃或兜底默认值** |
| 去重 | content-hash 精确去重 + simhash 近重复聚类 | — |
| 入库 | 幂等 upsert（以 content_hash 为键）；每次导入产出 ImportReport（文件数/条目数/拒绝数/人审数） | — |

**License 门禁在代码里强制**：sources 注册表每条带 `allowed_use ∈ {answers, stems_only, reference_only}`（见 research/02 §5）；`reference_only`（GPL/NC）直接抛 `LicenseViolation`，`stems_only` 强制 `answer_provenance=generated` 并保留来源署名。

## 4. 功能规格（按完整产品描述；交付批次见 §9）

### F1 面经知识库
开源仓库导入器 · 牛客公开页采集（SSR 话题页为种子，低频+robots 合规）· linux.do JSON API/RSS 采集 · 手动摘录入口 · LLM 结构化抽取（公司/岗位/轮次/问题树/追问链）· 混合检索（Meili 关键词 + pgvector 语义）与 RAG 问答 · UGC 投稿（公开化后）。
**验收**：结构化面经 ≥500、字段抽检准确率 ≥90%、一次"字节 Agent 实习问什么"问答可溯源到具体面经条目。

### F2 题库（richness 见 §3）
题目 CRUD 与 12 标签族（LLM基础/Transformer/训练微调/RAG/Agent/MCP与工具调用/多智能体/推理部署/评测/手撕/场景设计/HR面）· 公司-岗位-频率三维筛选与频率榜 · 自测模式（会/模糊/不会 → SM-2）· 手撕专项（编辑器 + 参考实现 diff 对比）· 闪卡/Anki 导出（genanki）· 爆料众包（后期）。
**验收**：≥3000 题带标签与来源；支持"公司×标签"双维筛选；频率榜数据可追溯到面经条目。

### F3 AI 考官模拟面试
简历押题（解析→声明抽取→预测提问树）· 厂商 persona（阿里系追问多 Agent 协作与 RAG 实现；字节从简历深挖工程链路）· 面试流程状态机（opening→self_intro→project→knowledge→scenario→reverse→closing）· 追问策略（每题追问链 3–4 层 + 4 级提示降级 + 自适应难度）· 多维评分报告（理解深度/表达结构/知识盲区/量化口径严谨性）· 失分点回流 F6 · 语音（LiveKit+STT/TTS，后期）· 反问环节助手。
**验收**：30 分钟文字模拟面试产出 ≥8 条追问链；报告失分点与人工金标准（research/04 §3）一致率 ≥80%。

### F4 项目拷打（核心差异化）
离线备课流水线：clone → 噪声过滤（gitingest/repomix 思路）→ tree-sitter 符号图 → **aider 式 repomap（PageRank=考点权重，references/aider/aider/repomap.py 为移植底本）** → cAST AST 分块 → pgvector → deepwiki-open 式架构 wiki（结论带源码引用）→ git 归属分析（`git log --author`）。
简历对齐：声明 ↔ 证据映射 → 注水疑点清单（首个金标准：research/04 §5）。
在线拷打循环：pi Agent + 只读工具面（read_file/grep/list_dir/get_repo_map/get_wiki_section/get_resume_claim/get_suspicion）· 出题蓝图 = repomap 权重 × JD 相关度 × 声明覆盖度 × 疑点 · "回答 vs 代码证据"实时质证 · 证据链评分报告（每项评分附 文件:行号）· trajectory 回放。
**验收**：作者真实 repo（OpenSOP Agent / Local Window Copilot）全流程跑通；疑点清单对 §5 金标准 ≥4/5 判定正确。

### F5 简历工作台
JD 匹配度（关键词缺口/经历映射）· 简历押题（与 F3 共享解析器）· 简历-题库联动刷题清单 · 量化口径缺失检测。

### F6 学习追踪
错题本 + SM-2 间隔重复 · 标签掌握度图谱 · 面试失分点回流 · Anki 导出 · 今日复习计划。

## 5. 服务契约

### 5.1 apps/api（FastAPI）
- `POST /api/ingest/sources/{slug}/run`：执行导入（生产经 arq 队列）；`GET /api/ingest/sources`：注册表与 license 状态
- `GET /api/questions?tag=&company=&q=&kind=&limit=&offset=`；`GET /api/questions/{id}`（含追问链/相似题）
- `GET /api/experiences?company=&role=`；`GET /api/search?q=`（Meili+pgvector 混合）
- `POST /api/sessions/{id}/report`：读取 session JSONL → 评分 rubric（结构化输出）→ 落盘
- `POST /api/resumes/parse`（pypdf → 声明抽取）；`POST /api/repos/{id}/prepare`（备课流水线，Phase G1）
- 内部工具端点（供 agents 只读工具调用）：`/internal/repos/{id}/file`、`/grep`、`/repomap`、`/wiki/{section}`、`/claims`、`/suspicions`
- LLM 网关：`complete()` / `complete_structured(schema)`；**显式单 provider，不做模型静默降级**；结构化输出失败→单次带校验错误重试→仍失败抛 `StructuredOutputError`；全部调用记 `llm_calls`（token/延迟/用途）

### 5.2 apps/agents（Node, pi 运行时）
- `POST /sessions {mode, persona, config}` → `{id}`；`POST /sessions/:id/turn {text}` → SSE（text_delta / phase / followup_level / tool_activity 事件）→ `{reply, phase}` 收尾
- 状态机与追问阶梯是我们自己的代码；LLM 循环、工具执行、事件流、provider 是 pi 的代码（MIT，钉版 0.84.3）
- 会话以 JSONL append-only 落盘 `data/sessions/{id}.jsonl`（回放/审计/评分输入）
- F4 拷打模式与只读工具在 Phase G1 挂载；未就绪时路由返回显式 501（不做假实现）

### 5.3 数据模型（核心表，apps/api/alembic 管理）
users · companies · tags(树) · questions(kind/difficulty/answer_provenance/source/content_hash) · question_tags · question_followups（追问链）· question_companies(频率) · experiences(+items 问题树) · resumes · resume_claims · projects · repo_artifacts · suspicions · interview_sessions · messages · review_cards(SM-2) · mastery · golden_cases · sources(license 门禁) · embeddings(kind/ref/model/Vector) · llm_calls(用量)

## 6. Web UI 设计规范（apps/web）

**设计基调**：Linear 式暗色优先、键盘优先、信息密度高、动效克制；中文排版以 Noto Sans SC 兜底。参考对象：Linear（导航/命令面板/密度）、Vercel/Geist（排版与代码呈现）、shadcn/ui（组件基调）、DeepWiki（源码引用式证据展示）、CodeTop（表格筛选范式）、Claude/ChatGPT（对话流与工具活动展示）。

**技术栈**：Next.js 16 App Router · TypeScript strict · Tailwind v4（`@theme` 设计令牌）· shadcn/ui 组件基调（Radix 原语）· cmdk 命令面板 · TanStack Table（题库/面经表格）· Recharts（rubric 雷达/掌握度）· shiki（代码证据高亮，文件:行号锚点）· lucide-react 图标。

**设计令牌**（globals.css 单一来源）：`canvas #0b0c0e / surface #101114 / surface-2 #16181c / border #23262c / text #e6e8eb / text-dim #9aa0a8 / accent #6c8cff`，语义色 success/warn/danger；暗色为默认，预留 light 主题变量组。

**关键界面**：
1. **工作台 Dashboard**：掌握度热力（12 标签族）、今日复习队列、最近面试/拷打报告卡
2. **题库**：命令面板（⌘K 全局跳转）+ 三维筛选表格（公司/标签/题型）+ 刷题模式（自答→对照→自评）
3. **面经**：结构化卡片流（公司-岗位-轮次徽章 + 问题树折叠）+ 右栏 RAG 问答（答案引用面经条目）
4. **面试室**：对话流 + 阶段进度条（状态机可视化）+ 追问深度指示 + 工具活动侧栏（拷打时展示"面试官正在翻阅 src/xxx.py:42"）+ 结束后一键报告
5. **拷打报告**：rubric 雷达图 + 证据链（每条结论可跳转文件:行号，shiki 高亮）+ trajectory 回放时间轴
6. **简历工作台 / 复习计划**：JD 对比视图、SM-2 队列日历

**交互原则**：所有列表可键盘导航；破坏性操作需确认；流式输出逐 token 渲染；空态/加载态/错误态为一等公民（不允许白屏兜底）。

## 7. 工程原则（D5，写进 CI 可检查的部分）

1. **禁正则硬编码**：文档/HTML/代码一律结构化解析器（mistune AST / selectolax DOM / tree-sitter）；字符串规范化用 unicodedata 与 str 方法；确需字符级 token 匹配时必须集中在唯一模块并有注释论证。
2. **禁 fallback 堆砌**：
   - 错误必须类型化（`AppError` 族 / TS `Result` 与 typed error），API 层统一 problem-details 响应；**禁止 `except Exception: pass`、禁止静默默认值**。
   - 重试只存在于 LLM 网关一处（结构化输出校验失败单次重试）与采集器的显式退避策略，其他调用失败即失败。
   - 模型/供应商**显式配置**，不做"主模型挂了换备胎"式的隐式降级——可用性靠部署多实例，不靠掩盖错误。
   - 管道幂等：导入以 content_hash upsert，重跑安全；长任务（备课流水线）分步 checkpoint（repo_artifacts 记录产物）。
3. **边界校验**：所有外部输入（HTTP body、LLM 输出、爬取内容）过 Pydantic/Zod；内部类型 SQLAlchemy 2.0 Mapped / TS strict。
4. **质量闭环**：golden_cases 覆盖抽取（F1）、标签、押题、疑点判定（research/04 为金标准）；CI 跑单测 + golden 回归 + ruff/tsc。

## 8. 源码复用地图（D7）

参考源码已克隆至 `references/`（全部 MIT/Apache 或仅文档），分三级使用：

| 级别 | 来源 | 用法 |
|---|---|---|
| 直接依赖 | `@earendil-works/pi-agent-core` 0.84.3、`@earendil-works/pi-ai` 0.84.3（deepseek/moonshotai/qwen provider 原生） | apps/agents 的 agent 循环/工具执行/事件流/provider |
| 移植 | aider `repomap.py`（867 行，Apache-2.0）：tree-sitter 符号图 + personalized PageRank + token 预算二分 | Phase G1 移植为 `apps/api` 的 repomap 模块，文件头注明来源 |
| 移植/参考 | cAST 分块算法（arXiv 2506.15655）：AST 递归 split-then-merge | G1 向量索引切分器 |
| 结构参考 | deepwiki-open（MIT）：clone→分块→embedding→wiki 管线与 prompt 模式 | G1 wiki 生成 |
| 结构参考 | gitingest / repomix（MIT）：仓库遍历与噪声过滤清单 | G1 摄入过滤器 |
| Prompt 改编 | The-Interview-Mentor（MIT）：阶段机、4 级提示、rubric 文案 | F3 prompt 模板底稿（文件头注明改编自该项目） |
| 架构思想 | DeepSeek Harness（官方架构文档，references/deepseek-harness/docs/）："一切皆插件"、append-only 会话日志、Minimal 工具面 | 代码组织与会话设计，不做运行时依赖 |
| 反面约束 | AGPL 项目（interview-guide） | 只参考设计，禁止复制代码 |

## 9. 里程碑（垂直切片，架构完整、逐层点亮）

| 阶段 | 内容 | 出口标准 | 状态 |
|---|---|---|---|
| **P0 基座** | 三服务脚手架、docker-compose、核心数据模型+Alembic、LLM 网关、设计令牌与 UI 壳、pi 运行时接入、一键启停脚本 | api 启动建表；agents 可开 session 对话；web 壳可导航 | ✅ 2026-08-28（全栈实测：stop/start 幂等循环、健康检查、pi 集成 tsc 零错误） |
| **K1 知识核心** | F1 导入器（11 源注册+license 门禁）+ 增量导入（source_files 收敛记账）+ LLM 结构化抽取（思考开关/大 max_tokens）+ Meili 索引与全文检索 + F2 题库查询/标签/公司筛选 + **厂商分类管道**（24 厂商种子 + AI 推断标注 + 词表硬校验）+ **算法题接入**（kind=algorithm + "算法"标签族 + LeetCode Hot100 种子，供 I1 面试现场手撕调用） | 题库 ≥3000、面经 ≥500（§3 表格）；导入幂等可增量重跑 | ✅ 2026-08-29 管道全线打通并实测（faq-of-llm-interview 首源 128 文件；其余源经 `scripts/import_source.py --all` 后台持续灌库；厂商标注 AI 推断 freq=1，待面经挖掘校准） |
| **I1 面试循环** | F3 状态机+追问阶梯+persona、简历解析押题、评分报告、失分点回流；**面试官从题库组卷（含 kind=algorithm 手撕抽题）** | 30 分钟模拟面试+报告达 §4 验收 | 🟡 进行中（**闭环已打通**）：组卷 `POST /api/interview/plan`（公司频率榜+track 筛选，50ms）→ agents **题单驱动模式**（队列出题/含糊追问/打满跳题/question 进度事件，5 轮实测 0.8-1.3s/轮）→ 评分报告端到端实测（rubric 五维+原话证据+带标签复习建议）。待做：简历解析押题、报告页 UI、失分点回流 SM-2 |
| **G1 项目拷打** | 备课流水线（repomap 移植/cAST/pgvector/wiki/git 归属）、疑点映射、只读工具面、拷打 agent、证据链报告 | 真实 repo 全流程达 §4 验收 | 未开始 |
| **L1 学习闭环** | F6 SM-2/掌握度/Anki 导出、F5 简历工作台、Dashboard 完整版 | 失分→复习→掌握度更新闭环 | 未开始 |
| **P1 公开化** | 多用户、UGC 爆料、语音（LiveKit）、岗位聚合评估 | 按 §10 合规重审 | 未开始 |

**K1 遗留（转入 I1 期间的质量迭代）**：① 存量题标签重打标与 track/厂商回填（进行中：统一分类守护逐批处理，进程见 logs/import-classify.log）；② 厂商标注为 AI 推断（宁缺毋滥 prompt 但通用题易挂大厂），需面经事实对校准频率榜；③ 导入仍为同步内联执行，超大源建议切 arq 队列（端点语义不变）；④ 牛客/linux.do 采集器（K1 计划内，随面经管道 F1 后半实现）。

**2026-08-29 增补（题库组织升级，用户驱动）**：
- **岗位大类维度**：`questions.track` ∈ {大模型应用, 大模型算法, 大模型应用算法, 通用基础}；新导入题由抽取管道直接判定（qa_extract track 字段），存量题由统一分类管道回填（`POST /api/ingest/classify-companies` 一轮同时产出 track + companies，只补空值不覆盖）。
- **厂商 logo**：用户素材 18 家（zip 为 GBK 文件名，按清单顺序映射）落至 `apps/web/public/logos/{slug}.png`；`companies.logo` 列 + `GET /api/companies`（含题数）驱动题库页公司横条；缺素材的厂商（DeepSeek/Kimi/MiniMax/智谱/阶跃等）UI 显示首字占位，待用户补图。
- **来源标记**：`_source_out` 输出结构化来源——GitHub 渠道只显示仓库名不渲染外链（用户要求）；LeetCode 题标"LeetCode Hot100"；未来小红书/知乎/论坛/抖音渠道经 `meta.source_url/source_channel` 渲染可跳转链接。
- **配置健壮性**：api 的 .env/data 锚定自身路径（不再依赖 cwd），后台任务可从任意目录启动；导入 runner 对非 JSON 响应免疫（熔断计数而非崩溃）。
- **分类收敛语义修复**：分类判据从"无公司标注"改为"track 为空 OR classify_attempted_at 为空"——旧判据会把"LLM 已判定无把握厂商"的题永远重选，阻塞后面全部积压（守护误报追平）。`questions.classify_attempted_at` 列标记尝试即出池。
- **题库页体验补齐**：`GET /api/questions/stats` 输出 track/kind/tag facet 计数；前端分页器（页码窗口+每页 20/50/100）、岗位大类与题型徽章带数量、"未分类 N（回填中）"诚实计数。商汤 logo 追加。
- **2026-08-29 续**：① 厂商 logo 补齐至 **24/25**（DeepSeek/华为/蚂蚁/智谱/讯飞/月之暗面/商汤高清/拼多多/小米/MiniMax 已接入；仅阶跃星辰待素材）；② **track 增加"视觉算法"**（CV/CNN/ViT/多模态），存量 track 全量重置重判；③ 标签归一（tag_vocab 规范词表 + 别名表 + normalize_tags 脚本，修复小写漂移导致的 RAG/Agent 筛选零命中）；④ 题库页搜索置顶、厂商瓷片加大、标签 chips 由真实计数驱动；⑤ 配置/data 目录全部锚定仓库根（cwd 无关）， agents 会话目录与 api 对齐，导演回声泄漏做确定性清理。
- **2026-08-29 续二（同源代理架构，根治题库页 Failed to fetch）**：浏览器跨端口直连后端在真实浏览器环境（系统代理/端口漂移叠加）下不可靠。改为 **Next.js rewrites 同源代理**：`/api/*`→api、`/agents/*`→agents，前端只与 web 端口通信（SSE 流式经代理实测可用）；`start.ps1` 每次启动把实际解析端口写入 `.env.local`（API_PROXY_TARGET/AGENTS_PROXY_TARGET）并新增**启动前端口清障守卫**（本项目进程占用目标端口即清理——Next16 dev 单实例锁会让新实例静默退出，是多次"重启无效"的元凶）。仓库已推送：github.com/fjnuslw/WenQu（git 代理配置 127.0.0.1:7897）。
- **2026-08-29 续三（性能优化 + I1 闭环打通）**：
  - **性能**：调研与决策记录见 `search/前端性能优化调研.md`——页面切换卡的主因是 dev 模式按需编译，**默认切生产模式**（next build+start，start.ps1 自动构建，`-Dev` 保留开发模式），实测页面 22ms、代理 API 45ms；筛选卡的主因是无防抖+清屏闪烁，落地 **300ms 防抖 + keepPreviousData 等价实现**（拉取期间旧列表置灰），路由级 loading.tsx 兜底。
  - **端口策略定稿**：固定冷门段 23480-23482/24432/27700/26379；启动前项目级进程清障（按命令行清理孤儿 tsx/uvicorn）+ 端口清障 + 外部占用显式失败（不做自动漂移——漂移曾导致代理目标写坏与双实例并存）。
  - **同源代理定稿**：`/api/*` 走 rewrites；`/agents/*` 走专用 Route Handler（node:http + keepAlive:false——undici 连接池在 SSE 流结束后复用会被上游判 400，成功/失败交替出现）。
  - **I1 闭环实测**：组卷 50ms → 题单驱动面试 5 轮（0.8-1.3s/轮）→ 评分报告准确识别答非所问并给出带标签复习建议。
- **2026-08-29 续四（问答助手 agent 闭环 + 提交者归属修正）**：
  - **问答助手（题库页 × agents 闭环）**：题目卡片"问助手"按钮（二次确认）→ `mode=answer` 会话（挂载 web_search 工具：Bing 国内站 + cheerio DOM 解析，无 key 国内可达）→ 解答结构化（概念→原理→追问方向）、引用来源、搜索受限时诚实降级（声明把握度不编造）。web 侧 chat-room 复用（答题模式标签/自动首问）。
  - **提交者归属**：git 身份切换为 fjnuslw（276824652+fjnuslw@users.noreply.github.com），历史 commit 经 filter-branch 重写并强推。
  - 已知限制：Bing 对 bot 查询偶发返回低质结果（助手会诚实声明），后续可升级 Tavily/博查 API（需 key）。
- **I1 开工（第一块：评分报告）**：`POST/GET /api/sessions/{id}/report`——读取 agents 会话 JSONL → LLM 多维 rubric（理解深度/设计决策/表达结构/诚实度，带原话证据）→ 评分+失分点+带标签的复习建议 → 持久化 interview_sessions.score。端到端实测通过（真实会话两轮 → 报告质量达标）。失分点回流 SM-2（F6）据此推进。
- **2026-08-29 续五（问答助手 UI 落地验证 + 陈旧构建自动重建 + 题单状态机修复）**：
  - **"问助手"按钮不可见的根因与修复**：web 默认生产模式，而 start.ps1 只在 BUILD_ID 缺失时构建——按钮代码晚于上次构建 → 服务的是陈旧产物。新增**源码 mtime vs BUILD_ID 自动重建检测**（apps/web/src、next.config.ts、package.json 任一比产物新即重建），删除"已有产物即跳过"的静默分支。
  - **UI 美化落地验证**（浏览器实测 /bank 生产构建）：题目卡"问助手"按钮 40 处可见；厂商瓷片放大（logo size-14、字节 1069/阿里 922/腾讯 715/Google 435/DeepSeek 340/微软 334/百度 108）；全局字体栈升级（Inter/Segoe UI Variable/PingFang SC/微软雅黑，tabular-nums、行高 1.65、标题 letter-spacing）；题干 15px。共 22679 题。
  - **题单驱动模式状态机修复**：追问命中时误入 else 分支直接置 closing（与追问指令矛盾）、队列耗尽时 throw 越界。修正语义：含糊→原题追问不推进队列；有效回答/追问打满→出下一题；**队列耗尽→进入 closing 并在后续轮次稳定维持**（重复播报收尾指令无害）。
  - 提交：db91173（fix agents）、9c01f41（feat web+脚本），fjnuslw 推送 main。

## 10. 合规与 License 策略

（同 v0.1，代码级门禁见 §3；要点：MIT/Apache 作底稿并署名；无 license 只取题干自写答案；GPL/NC 仅 reference_only；牛客低频+robots；linux.do 游客 API；小红书/抖音仅人工摘录；AGPL 只参考设计。）

## 11. 风险

1. pi 包迭代快 → 钉版 0.84.3 + 适配层隔离（apps/agents/src/pi.ts 单点接触 pi API）。
2. LLM 抽取/评分质量 → golden 回归 + 人审队列，禁止静默兜底掩盖问题。
3. 采集被阻断 → 多源冗余，单渠道失败不阻塞知识目标。
4. 双运行时（Python/TS）运维成本 → docker compose 固定拓扑；会话状态以 JSONL+Postgres 为单一事实源。
5. 求职季时间预算 → 垂直切片各阶段独立可用，K1 完成即有日常价值。

## 附录 A：开源组件清单

| 用途 | 组件 | License | 引入阶段 |
|---|---|---|---|
| agent 运行时 | @earendil-works/pi-agent-core / pi-ai（0.84.3） | MIT | P0 ✅ |
| repomap | aider repomap.py（移植） | Apache-2.0 | G1 |
| AST 分块 | cAST 算法 | 论文 | G1 |
| repo wiki | deepwiki-open（参考） | MIT | G1 |
| 摄入过滤 | gitingest / repomix（参考） | MIT | G1 |
| 面试 prompt | The-Interview-Mentor（改编） | MIT | I1 |
| Anki | genanki | MIT | L1 |
| 语音 | LiveKit Agents SDK | Apache-2.0 | P1 |
| 基础设施 | pgvector / Meilisearch / Redis(arq) | PostgreSQL/MIT/BSD | P0 ✅ |
