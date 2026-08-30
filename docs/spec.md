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
| **I1 面试循环** | F3 状态机+追问阶梯+persona、简历解析押题、评分报告、失分点回流；**面试官从题库组卷（含 kind=algorithm 手撕抽题）** | 30 分钟模拟面试+报告达 §4 验收 | ✅ 2026-08-29 全链路实测：组卷 v2（公司频率榜 ∪ 简历考点押题 → LLM 定卷硬校验 + 面经追问素材 + 考察简报）→ agents 题单驱动面试（0.8-1.3s/轮，简报/简历要点/probes 首轮导演指令注入）→ 评分报告（rubric 五维+原话证据）→ 失分点自动回流 SM-2（续九）。简历解析管道 + 开始表单简历选择器已上线 |
| **G1 项目拷打** | 备课流水线（repomap 移植/cAST/pgvector/wiki/git 归属）、疑点映射、只读工具面、拷打 agent、证据链报告 | 真实 repo 全流程达 §4 验收 | ✅ **v1 全链路落地（2026-08-29/30 续十～十五）**：备课（目录/zip+异步进度）→ 声明质证 → 拷打（架构重心+自动开场+真读码审计+file:line 可点击核证）→ **证据链报告**（评分维度与失分点必带候选人原话/代码位置证据，浏览器渲染引用块+可点击定位，失分点回流 SM-2 保留锚点）。v2 待做：tree-sitter repo map、pgvector 语义检索、git URL 通道与归属分析、Anki 导出 |
| **L1 学习闭环** | F6 SM-2/掌握度/Anki 导出、F5 简历工作台、Dashboard 完整版 | 失分→复习→掌握度更新闭环 | ✅ 2026-08-30 收官：SM-2 回流+三键评分（续九）→ **掌握度统计**（按标签聚合，失分点带 tags 回流）/ **Anki 导出**（genanki .apkg）/ **JD 匹配度**（简历画像×JD→匹配分/已覆盖/缺口/建议，实测 88/100）/ **Dashboard 完整版**（题库/面经/复习/岗位大类真实统计） |
| **P1 公开化** | 多用户、UGC 爆料、语音（LiveKit）、岗位聚合评估 | 按 §10 合规重审 | 未开始 |

**K1 遗留（转入 I1 期间的质量迭代）**：① 存量题标签重打标与 track/厂商回填（进行中：统一分类守护逐批处理，进程见 logs/import-classify.log）；② 厂商标注为 AI 推断（宁缺毋滥 prompt 但通用题易挂大厂），需面经事实对校准频率榜（面经采集器已落地，可从 experiences.items 挖掘公司×题目共现）；③ 导入仍为同步内联执行，超大源建议切 arq 队列（端点语义不变）；④ 牛客/linux.do 采集器——**牛客已落地（续六）**，linux.do 被 Cloudflare 拦截显式失败，待浏览器级方案或人工摘录。

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
- **2026-08-29 续六（F1 面经采集器落地：牛客 SSR 通道打通，linux.do 游客通道被 CF 拦截）**：
  - **渠道架构**（`ingest/collect/`）：`PoliteClient` 合规客户端——真实 UA + 渠道级最小间隔（牛客 8s / linux.do 10s）+ **robots 门禁**（urllib.robotparser 标准库解析；robots.txt 不可获取=合规不可判定=拒绝采集，不默认放行）+ 显式代理配置 `GETOFFER_COLLECT_PROXY`（本机直连两个目标域名均 SSL 失败，实测需走本机 Clash，.env 已配，gitignore 内）。类型化错误族新增 `ComplianceViolation`（我们的闸门）与 UpstreamError 区分（上游拒绝）。
  - **牛客通道（实测打通）**：话题聚合页 SSR → feed 卡片解析（selectolax DOM：`a[href*=/feed/main/detail/]` → 标题=外层容器文本去预览前缀、正文=`div.placeholder-text`）→ LLM 结构化（is_interview_experience/公司/岗位/轮次/日期/结果/问题树含追问）→ `experiences`+`experience_items` 幂等入库（content_hash=sha256(NFKC(url+文本))，重跑 3 duplicates/0 inserted 实测）。公司归属与 companies 表 name+alias 精确匹配（网易/B站→哔哩哔哩 命中）；词表外（中科闻歌）诚实报告 `unmatched_companies`，不建新公司行。**页面事实修正 research/02 预期**：话题页卡片自带完整内容预览，但 `/feed/main/detail` 详情页是 JS 壳（游客无全文）→ 抽取忠于预览、截断不编造（prompt 规则：可见文本抽不出问题=非面经不入库）。
  - **linux.do 通道（实现完成，运行时诚实失败）**：Discourse 游客 `/t/{id}.json` → cooked HTML 经 selectolax 转文本；实测被 Cloudflare 挑战页 403 拦截——按 spec §10 显式失败（不绕过反爬/不带登录态），错误信息指明改走人工摘录；待浏览器级采集方案再启用。
  - **端点**：`POST /api/ingest/collect/{nowcoder|linux-do}?max_posts=N`（内联执行，与导入一致；切 arq 时语义不变）。**面经页**：experiences 读侧已有 API，web 页接真实数据（公司/轮次徽章 + 编号问题树 + 追问缩进 + 回答上下文注记 + 原帖外链）。E2E 全通：采集→抽取→入库→页面（3 帖：网易 17 节点/中科闻歌 14 节点/腾讯）。
- **2026-08-29 续七（思考流 + 输出真渲染 + 面经来源分类，用户试用反馈驱动）**：
  - **调研结论（pi × DeepSeek 思考流复用，用户指定的两步走第一步）**：pi-ai 0.84.3 原生支持 DeepSeek 思考协议——目录条目 `reasoning:true` + `compat.thinkingFormat:"deepseek"`（请求 `thinking:{type}`、响应 `reasoning_content` 流），适配层把增量映射为 `thinking_delta` 事件（api/openai-completions.js:405）；pi-agent-core `AgentState.thinkingLevel` 支持 minimal/low/medium/high/xhigh/**max** 七档，经 `initialState` 注入。零自研协议代码。
  - **思考流落地**：答题模式吃满 **max 档**（`AGENT_THINKING_LEVEL` 可调，非法值启动即失败）；面试官按模式分档 medium（短回复不值得 reasoning 开销——token 成本优化的第一杠杆）；thinking_delta 经 SSE 转发 + 会话 JSONL 落盘（thinking 字段）；prompt 显式要求**思考用中文**（用户要阅读思考过程理解解题路径）。实测：手撕 MHA 题思考 14.1s、reasoning 3479 tokens 全程右栏实时可见。
  - **输出渲染**：streamdown 2.6 + `@streamdown/math`（singleDollar 行内公式）+ `@streamdown/code`（shiki 双主题）；DeepSeek 的 `\(\)`/`\[\]` 定界符在代码栅栏外归一化为 `$`/`$$`（纯字符串替换，display-layer 关切）；globals 落暗色 markdown 排版（标题/表格/代码块/KaTeX 溢出）。**人机感治理**：prompt 重写为"学长划重点"人设 + 三段产出结构（**面试口头版**120-200 字可直接背 / 展开解析 / 可能的追问方向）+ 显式禁令（综上所述/总而言之/值得注意的是/满屏加粗/排比开头/emoji/过程性元话语）。实测回答零元话语、LaTeX 公式与 GFM 表格渲染正确。
  - **真流式修复（关键 UX bug）**：agents 同源代理原实现**全量缓冲** upstream body——max 思考的 40s 里浏览器只看到空气泡、SSE 计时归零（0.0s）。改为 ReadableStream 逐块转发（保留 keepAlive:false 的 400 修复）；Buffer 入队显式拷贝（池化 ArrayBuffer 视图不可直接引用）。
  - **可观测性**：每轮 usage（input/output/cacheRead/cacheWrite/reasoning）入会话 JSONL——token 开销与缓存命中从此有数（首轮 cacheRead=0 正常，追问轮可验证 DeepSeek 前缀缓存命中；实测单轮 reasoning 3479/output 4586，量化了 max 思考的成本结构）。附带修复：pi Agent 的消息数组在 `agent.state.messages`（`agent.messages` 不存在——此前 messages 兜底从未生效，被 streamBuf 主路径掩盖）。
  - **面经按来源分类**：Experience 补 source relationship，API 输出 source_slug/source_name/company_logo；页面来源 tab（数据驱动，新渠道自动出现）+ 公司筛选 chips（带 logo）+ 卡片（logo/轮次/来源标注/原帖外链）+ 问题树默认 3 题折叠展开。
  - 提交：ed2e246（agents 思考流）/ 9440852（web 渲染+流式）/ 1c99861（面经分类）。
- **2026-08-29 续八（面试智能体闭环 + web_search 根因修复 + 缓存命中率，用户驱动）**：
  - **web_search 根因（用户从思考过程发现）**：思考流暴露了"搜索引擎一直返回 undefined 相关内容"——探针实锤 pi-agent-core 的 `AgentTool.execute` 签名是 `(toolCallId, params, signal?, onUpdate?)`，我们把首参当成了参数对象，`query` 恒为 undefined → Bing 真的在搜 "undefined" 这个词。修复后实测搜索质量正常（百科/知乎带日期结果）。**教训：工具签名的静态 cast 绕过了类型检查；思考流作为可观测面第一次就抓到了纯 API 误用。**
  - **面试智能体闭环（用户定位的核心：面试官结合简历×面经×题库给完整面试）**：
    - 简历管道（`/api/resumes`）：PDF 上传（pypdf，+python-multipart）→ LLM 结构化画像（姓名/方向/技术栈/项目要点/exam_tags 只能选题库标签词表）→ resumes.parsed + resume_claims（项目要点即"声明"，G1 拷打的声明-证据映射数据源）。实测真实简历：6 项目/5 考点标签全对。
    - 组卷 v2（`POST /api/interview/plan` 带 resume_id）：候选池 = 公司频率榜 ∪ 简历 exam_tags 命中题 → **LLM 定卷**（押题配比/手撕场景至少各 1/从面经追问池为每题分配 0-2 条真实追问/写考察简报 brief），**id 越池硬校验丢弃**、不足按频率榜确定性补齐。追问池来自该公司 experiences 的追问链节点（真实面经）。实测 brief 精准命中简历（EMNLP/IN-Retriever）；LLM 对不相关追问宁缺毋滥正确拒绝（当前追问数据少：13 条面经仅 3 条追问链，随采集增长）。
    - agents 消费：PlanQuestion.probes → questionDirective（"来自该公司真实面经，择用改写"）；persona.brief/resumeHighlights → **首轮导演指令注入一次**（之后进入可缓存历史）；开始表单加简历选择器。E2E：简报/要点/probes 全部进入导演指令，面试官正常出题追问。
  - **缓存命中率（turn2 实测 72%）**：`sessionId` 转发 provider（pi cache-aware hook）+ 会话内 append-only 前缀自然命中；关键优化：brief/简历要点原设计放 systemPrompt——**每会话不同 → 杀死跨会话首轮缓存**，已移到首轮导演指令（systemPrompt 只留稳定的公司/岗位/规则头，同 persona 重开面试首轮即可命中）。日志逐轮记录 input/cacheRead/cacheWrite/reasoning，命中率从此可观测。
  - 提交：b91a957（web_search 修复）/ 1e3128b（面试智能体闭环）。
- **2026-08-29 续九（框架收束：F6 失分点回流 SM-2 + F5 简历工作台 UI，I1 收口）**：
  - **F6 失分点回流（L1 第一块）**：`review_items` 表（SM-2 全字段：ease/interval/repetitions/lapses/due_on）+ `POST /api/sessions/{id}/report` 自动把 weaknesses 回流为复习条目。幂等语义修正：按**会话**去重（该会话已回流即跳过）——重生成报告的 LLM 措辞不同，文本哈希去重挡不住重复（实测踩坑：同一会话两次生成产出不同措辞的 4+4 条）。`/api/review`：到期清单（due/all）+ `/{id}/grade`（忘了/模糊/掌握 → q=1/3/5 经典 SM-2：q<3 重学+lapse，否则阶梯放大间隔并调 ease）。实测：掌握 → ease 2.5→2.6、间隔 1 天、明天到期。
  - **复习队列页**（`/review`，侧边栏新入口）：今日待复习/全部切换、逾期徽章、SM-2 参数展示（间隔/ease/第 N 次/遗忘次数）、三键评分（到期视图评分即出队）、来源会话可溯。
  - **F5 简历工作台 UI**（`/resume`）：PDF 上传（FormData 经同源代理，python-multipart）→ 简历列表 chips → 画像展示（技术栈/考点标签/面试官深挖点/项目要点——要点即 G1 声明底稿）。此前简历只能 curl 上传，闭环入口补齐。
  - **I1 里程碑收口** ✅：组卷（简历押题×面经追问×频率榜）→ 题单驱动面试 → 评分报告 → 失分点回流 SM-2，全链路一次打通。剩余为质量迭代：报告独立页（当前为面试室内联面板）、30 分钟长面试验收。
  - 提交：本笔（F6+F5+I1 收口）。
- **2026-08-29 续十（G1 项目拷打 v1 落地，用户核心思想产品化）**：
  - **竞品复核（research/06）**：2026-08-29 复检，"读你的仓库再拷打你"的市场空白仍存——竞品全部停在简历/JD 文本层（han-dreamer、interview-skills、FoloUp、interviewing.io）；最近似的 yizucodes/interview-agent 只对项目文档 RAG 不对代码质证。差异化定位：**懂项目、懂提问的 agent**——先像新入职的资深工程师读明白仓库（备课），再像最较真的面试官对照简历声明逐条质证。
  - **备课流水线（api `grill/prep.py`）**：zip 上传（Zip Slip 防护：绝对路径/盘符/.. 一律拒绝）→ 噪声过滤（目录/扩展名/大小三道闸 + 400KB 总预算）→ 重要度排序收集（README>入口>src 下大文件）→ LLM 分批备课：每模块产出 **职责/技术点/实现细节题/方案对比题（真实替代方案）/缺失质询题（先确认代码确实没做）**；可选 resume_id → 简历 claims × 备课 → **声明对照质证清单**（supported/suspicious/not_found + 质证问题）。产物落 Project + RepoArtifact（tree/briefing/claims 三 artifact）。
  - **拷打 agent（agents）**：`mode=grill`，只读工具面 `list_files/read_file/search_code`（路径监狱 resolve 校验 + 64KB 单文件上限，刻意排除 write/bash——dsh Minimal 启发）；备课产物经首轮导演指令注入（systemPrompt 只留稳定规则头，吃跨会话前缀缓存，实测新会话首轮 cacheRead=6144）；思考 high 档。**诚实纪律（实测踩坑修复）**：初版拷打官会宣称"已通读 server.ts"但实际零工具调用、行号从简报编造——加入"禁止声称已读未读文件、引用行号必须来自真实读取"规则 + **工具调用落 JSONL 审计**（tool_use 条目）。修复后实测 5 次真实读码、引用行号准确。
  - **E2E（用 WenQu 自身仓库做被拷打项目，127 文件/268KB）**：备课 95s 产出 16 模块（连本项目的 SSE 无心跳、会话无过期清理、prompt 无防注入全被抓为缺失质询题）；声明对照把简历 IN-Retriever 全部声明正确判 not_found 并生成"你说的 X 在哪"质证问题——**注水识别价值主张成立**。拷打两轮实测：先核对候选人回答与 queue.ts 一致 → 主动读 session.ts:183 发现无 AbortSignal → 质询"客户端断连后 LLM 继续跑事件堆积，清理机制呢"——查证式深挖（怎么实现的→边界→缺失）完整成立。缓存：turn2 cacheRead=9088。
  - **web**：/grilling 页（项目名+对照简历+zip→备课报告：总览/声明质证清单/模块拷打弹药→开始拷打）；ChatRoom grill 模式（"拷"头像/思考栏/回答拷打官占位）。
  - v1 取舍（research/06 §3）：tree-sitter repo map、pgvector 语义检索、git 归属分析 → v2（zip 无 git 历史；子串检索对中等仓库够用，Anthropic 立场支持 agentic search）；评分报告复用 I1（JSONL 同构）。已知缺口：会话历史回显（ChatRoom 客户端态不拉历史）、备课内联执行（大仓库 1-3 分钟，切 arq 时语义不变）、/grilling 页未接已备课项目列表。
- **2026-08-29 续十一（G1 体验收口：本地目录接入 + 简历替换 + /api 代理 30s 断连根治，用户反馈驱动）**：
  - **本地目录原位备课（dsh 式）**：`local_path` 表单字段（绝对路径）→ 服务端**原位读取零拷贝**（repo_path 即原目录，不再解压进 data/projects），项目名自动取目录名；本地部署形态下最自然的接入方式。zip 上传保留为辅助通道。E2E：`apps/agents` 目录 → 16 文件/10 模块/12 声明对照，95s。
  - **/api 代理 30s 断连根治**：长 POST（备课 95s）经 next.config rewrites 的 undici fetch 在 ~30s 被 ECONNRESET（web.err.log 实锤；此前"扩采 500"与"备课 500"同因，此前误判为重启撞车）——**/api 弃用 rewrites，改走与 /agents 同构的 node:http Route Handler**（app/api/[...path]/route.ts，keepAlive:false + 逐块转发），95s 长备课经代理实测全程 200。
  - **简历替换与隐私**：DELETE /api/resumes/{id}（行+声明+本地 PDF 文件）；/resume 页 chips 带 × 删除，"替换 = 删除后重新上传"；页头明示"文件只存本地 data/uploads（已 gitignore）"。**隐私核查：data/ 全目录在 .gitignore、git 零跟踪 PDF——用户简历从未进过 GitHub**。
  - **/grilling UI**：双模式 tab（本地目录推荐 / zip 辅助）、项目名可留空自动推导（修复"上传按钮莫名置灰"：此前要求先填项目名）、备课进度文案、repo_root 展示。
- **2026-08-29 续十二（G1 体验二期：异步备课 + 目录选择器 + 会话持久恢复 + 拷打文件侧栏，用户四点反馈）**：
  - **诊断"卡住"**：用户备课 `D:\AI_Workspace\weixin` 实际成功但耗时 3-4 分钟且页面零反馈；且微信小程序项目 49,700 文件中 miniprogram_npm 未被排除、md 文档吃光 400KB 收集预算（121 个入选文件 md/yaml 为主，源码反而没进）。
  - **备课异步化（A）**：POST 立即返回 project_id（status=preparing），asyncio.create_task 后台执行，Project.meta 分步更新（status/step/progress），GET /{id} 轮询；失败落 status=failed+error。前端轮询展示步骤。
  - **收集器修正（B）**：EXCLUDE_DIRS 补 miniprogram_npm/uni_modules/taro-dist 等；文档类（md/txt）单文件 8KB 截断，预算优先源码。
  - **文件管理器选择（C）**：`<input webkitdirectory>`（浏览器原生目录选择对话框）+ JSZip 客户端打包 → 走 zip 通道（浏览器安全模型拿不到绝对路径，本地 localhost 上传零成本）；粘贴路径保留为高级方式。
  - **会话持久化与恢复（D）**：agents 增 GET /sessions（列表：mode/persona/轮数/时间）与 GET /sessions/:id/history（JSONL 重放 user/assistant/tool_use）；ChatRoom 挂载即拉历史（刷新/换设备继续聊，会话在 agents 内存仍存活时直接续）；agents 重启后的历史会话只读回放。
  - **拷打文件侧栏（E）**：api 增 tree/file 端点（路径监狱，越界显式 400）；grill 模式右栏改双 tab（思考过程/项目文件——树浏览+行号查看器）；拷打官回复中的 `文件:行号` 引用渲染为可点击链接 → 打开侧栏对应文件并滚动高亮该行（dsh 式证据可核）。**已全部落地（4d7d3b0）**：E2E——异步备课（POST 立即返回 → 5 批 LLM 备课进度逐批上报 → ready）；agents 会话列表（30 条，含用户 weixin 拷打）与历史重放（含思考全文）；浏览器实测点击 `chat-room.tsx:66` 引用 → 右栏切文件 tab → 打开文件高亮定位第 66 行（拷打官 prompt 增引用格式约束 `相对路径:行号`）。收集器修正实测：web-app 备课 41 文件源码为主（此前 weixin 被 md 吃满预算）。
- **2026-08-29 续十三（拷打体验校准，用户两点反馈）**：
  - **自动开场（fd0f5a2）**：grill 会话进入面试室即自动发出引出语（"面试官您好，我是这个项目的作者，请开始拷打。"）——拷打官先开口，不再要求用户先说话；有历史（回放）或会话过期（agents 重启）时不自动发。
  - **考察重心校准（架构 ≠ 代码评审）**：用户反馈"过于细致、脱离面试范围"——拷打官原则重写：重心为**架构与设计决策**（模块划分与职责边界/选型理由与代价/数据流与协作/规模化与失败场景），三类题改为 设计决策/方案对比/架构质询；**函数级细节仅在候选人架构层含糊或存疑时下沉验证**。备课 prompt 同步改向（detail_questions 出架构题，不出函数题）。实测：重备 api 服务 16 模块零函数细节题（"app.state vs 全局变量的取舍""渠道注册表模式 vs if-else""为什么 FastAPI 而非 Flask"）；新会话第一问为"三服务为什么拆分、与单体相比的收益与代价"（纯架构权衡）。
- **2026-08-30 续十四（会话归位 + 项目管理 + 全局字体收敛，用户三点反馈）**：
  - **会话记录归位**：删除独立 /sessions 页（"太散"）——mock 会话进「模拟面试」页的"最近面试"板块，grill 会话进「项目拷打」页各项目卡片内（按 projectName 分组）；数据源不变（agents /sessions 列表）。
  - **已备课项目管理（dsh 式）**：GET /api/grill/projects 列表丰富化（status/file_count/时间/备课摘要）+ DELETE /api/grill/projects/{id}（库行 + artifacts + zip 解压目录；local_path 原位项目只删库不删目录）；项目卡片支持 一键再开拷打（复用已存 briefing，无需重备课）/ 查看备课 / 删除。
  - **全局字体收敛**：页面里 text-[11px]/text-[10px]/badge 堆叠导致层级混乱——统一为三级信息行（主 sm-medium-ink / 次 xs-ink-dim / 元 xs-ink-faint），非状态信息从徽章降为分隔点文字，收紧字号梯度。
- **2026-08-30 续十五（G1 收官：证据链报告）**：
  - **schema**：`EvidenceRef{kind: quote|code, quote, file, line}`；ReportScoreItem 与 weaknesses（WeaknessItem）必带 evidence；评分 prompt 升级——每条论断配**候选人原话逐字摘录**或对话中拷打官引用的 `文件:行号`（禁止臆造，须能在记录中逐字找到）。
  - **web 渲染**：报告面板每维度/失分点下渲染证据——原话=引用块，代码位置=可点击按钮（grill 会话点击跳侧栏文件定位）。
  - **回流**：失分点文本并入代码锚点（"…（见 apps/agents/src/session.ts:183）"）进 SM-2 复习队列，复习时可回看现场。
  - **E2E（wenqu2 两轮拷打会话）**：设计决策质量 2/5 挂证据 ["SSE 写得慢只是背压，事件都在内存里排着。"（原话）+ session.ts:183（代码）]；诚实度/理解深度等维度全部带原话；失分点"未主动识别缺失 AbortSignal"带代码锚点回流。浏览器实测证据引用块与可点击位置完整渲染。
  - 提交：a2b0177。**G1 里程碑 v1 收口** ✅。
- **2026-08-30 续十六（L1 收官 + 全站打磨）**：
  - **掌握度统计**（`GET /api/review/mastery`）：按标签聚合 SM-2 状态（mastered=repetitions≥2 且最近掌握 / learning / due）；失分点回流时 LLM 从题库词表选 tags（ReviewItem.tag 维度列，旧数据"未分类"诚实展示）。/review 页顶部概览卡：掌握进度条 + 分标签 N/M。
  - **Anki 导出**（`GET /api/review/export.anki`，genanki/MIT）：复习队列 → .apkg 下载（正面=失分点问题，背面=详情+SM-2 状态+来源会话），实测产出合法 APKG（file 验证）。
  - **JD 匹配度**（`POST /api/resumes/{id}/jd-match`）：简历画像 × JD 原文 → 匹配分（0-100）/已覆盖（引简历项目证据）/缺口（按重要度）/加分项/可执行建议。实测用户简历 × Agent 岗 JD：88/100，matched 精准到 OpenSOP/飞书 Agent/记忆系统，gaps 准确（embedding 微调/RLHF/SGLang）。/resume 页 JD 卡片。
  - **Dashboard 完整版**（`GET /api/stats`）：题库总量/track 分布、面经数、复习队列（到期/总数/已掌握）、覆盖岗位大类——真实数据卡片（22,679 题/13 面经）+ 复习引导语按到期数自适应。
  - **打磨**：README 重写功能全景（六模块入口表 + 代理配置说明）；全部服务重启 E2E 通过。
  - 提交：本笔。**L1 里程碑收口** ✅——四条里程碑（K1/I1/G1/L1）全部达成。
- **2026-08-30 续十七（P1 语音 v1：浏览器原生方案，用户驱动）**：
  - **调研结论**：原计划 LiveKit Agents SDK 对本地单用户平台过重（需服务器编排）。2026-08-30 复核：**SpeechSynthesis（TTS）** 主流浏览器广泛支持、zh-CN 音色可用、零依赖零成本（[MDN](https://developer.mozilla.org/zh-CN/docs/Web/API/Web_Speech_API/Using_the_Web_Speech_API)、[张鑫旭](https://www.zhangxinxu.com/wordpress/2017/01/html5-speech-recognition-synthesis-api/)）；**SpeechRecognition（ASR）** Chrome/Edge 支持中文实时转写，识别请求由 Google/Azure 云处理（需网络，[Chrome 官方](https://developer.chrome.com/blog/voice-driven-web-apps-introduction-to-the-web-speech-api?hl=zh-cn)）。v1 定案：**纯前端 Web Speech API**——语音输入（麦克风按钮 + 实时转写进输入框）+ TTS 朗读面试官回复（可开关），零后端改动；浏览器不支持时诚实隐藏（功能检测，非报错）。v2 若需离线/高精度 ASR 再评估 whisper.cpp 本地或云 ASR。

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

## 2026-08-30 续十八（面经渠道扩充：牛客多话题 / CSDN / linux.do RSS / 人工摘录）

- **牛客多话题**：从单一“大模型面经”扩为 4 个逐页人工确认的真实话题（大模型面经、Agent 面经、AI 项目拷打、实习面试记录），仍保持 8 秒最小间隔。为避免第一个首页吃满配额，按剩余条数/剩余话题动态分配配额。实测 `?type=new&page=1/2/3` 的 16 条帖子 URL 集合完全相同，SSR 忽略 `page`；因此只采各话题最新首页，不猜测滚动接口。牛客偶发返回 HTTP 200 的约 6KB 空壳，允许同 URL 一次受限重试，两次仍无 feed 则抛 `UpstreamError`。robots 允许 subject/feed，`/search` 实测被 `ComplianceViolation` 拒绝。
- **CSDN 精选**：新增 `csdn` 渠道，12 秒最小间隔；`blog.csdn.net` robots 门禁允许已审核文章路径，正文稳定 SSR 在 `#content_views`，统一用 selectolax DOM 提取。只选单公司/个人面经，避免把多家公司汇总误并为一场；只在 `raw_text` 内部检索并保留原帖 URL，不生成正文转载页。3 篇首次采集全部入库，立即重跑 3 条全部去重。
- **linux.do RSS**：`linux-do` 改为依次尝试 `top.rss` / `latest.rss`，XML 用标准库解析；若正文 JSON 被 CF 拦则只用 RSS 摘要并显式写入 meta。2026-08-30 实测两个 RSS 均为 Cloudflare 403，端点返回明确的 502 `upstream_error`，没有指纹、cookie、登录态或其他绕过。
- **知乎评估**：对公开回答页走 PoliteClient 实测，robots 明确禁止 `/question/.../answer/...`，故不注册自动渠道。知乎内容仍可通过人工摘录端点进入。
- **人工摘录闭环**：新增 `POST /api/ingest/collect/manual`，支持小红书/抖音/知乎/脉脉/朋友分享五种来源；只消费用户提交的文本、可选溯源 URL 和日期，绝不请求原站。自动采集与人工文本共用 `ingest_post_previews`，因此共享 LLM 忠实抽取、公司词表匹配、content_hash 幂等和问题树入库；人工确认日期优先于模型推断。`/experiences` 新增“人工摘录”弹层，导入后刷新来源 tab。
- **数据与验收**：本轮后共 20 条面经：牛客 16（公司匹配 10、主问题 164、追问 10），CSDN 3（匹配 2、主问题 90），小红书人工摘录 1（匹配 1、主问题 3、追问 1）。真实端点首次/重跑分别验证新增与 `inserted=0`；资料广告样例返回 `skipped_non_experience=1`。后端 11 项 pytest、ruff、py_compile、前端 TypeScript 与 Next production build 全部通过；浏览器验证人工来源 tab、日期与追问树正常。
- **用户授权后的浏览器辅助扩充**：用户明确授权后，通过已登录的可见浏览器低频逐帖检索与翻图识别，没有新增小红书自动采集器、隐藏接口调用、Cookie 提取或无人值守翻页。人工审核并导入京东、字节、腾讯、百度、面壁智能、淘天、小红书、地平线 8 篇真实面经，首次全部 `inserted=1`，原样重跑全部 `duplicates=1, inserted=0`。当前共 28 条面经，其中 `manual-xhs` 9 条、153 个主问题和 1 个追问；`/experiences` 实测来源 tab 为 `小红书人工摘录 9`，筛选结果 `9/28`。图片密集长帖仍受单篇 30 题 schema 上限约束，面壁智能 9 图中的后续问题已在交接总结列为遗留，未伪造或静默拆成多场面试。
- **小红书第二批与抖音人工扩充**：小红书第二批再导入 15 篇、254 个主问题；用户完成抖音登录后，以同样的可见浏览器低频逐帖方式审核腾讯、美团、字节、米哈游、联想、大疆、哔哩哔哩、美的和一条真实小公司 Agent 岗记录，共导入 9 篇、114 个主问题。抖音批次首次均 `inserted=1`，原样重跑均 `duplicates=1, inserted=0`。当前共 52 条面经，`manual-xhs` 24 条、`manual-douyin` 9 条；页面实测显示 `52/52`、来源 tab `抖音人工摘录 9`，每条保留可跳转原帖。全程未访问隐藏接口、Cookie 或本地存储，也未把浏览器步骤写成自动采集器。
- **抖音第二批与知乎首批继续扩充**：继续用已登录的可见浏览器审核“大模型面经”“AI 应用开发面经”等多组关键词，抖音新增腾讯、字节飞书/海外直播、阿里、蚂蚁、美团、百度、快手、网易、小鹏及创业公司等 13 篇真实面经、155 个主问题；首次全部 `inserted=1`，原样重跑全部 `duplicates=1, inserted=0`。用户随后自行完成知乎登录，再低频逐篇核验并导入字节多模态/豆包、腾讯混元、阿里夸克、通义实验室、淘天多模态和美团等 8 篇、162 个主问题；首次 8 篇全部新增，重跑 8 篇全部去重。当前共 73 条面经，`manual-douyin` 22 条、269 个主问题，`manual-zhihu` 8 条、162 个主问题；页面实测显示 `73/73`、来源 tab `抖音人工摘录 22 / 知乎人工摘录 8`。全程只阅读登录后可见页面，不读取 Cookie/本地存储、不调用隐藏接口，也不把浏览器步骤自动化进仓库。

## 2026-08-30 续十九（27 届秋招官方网申入口进题库）

- **背景**：27 届秋招集中开启期，用户逐家核验了 24 家大模型相关公司的官方校招 / Early Career 网申入口（覆盖字节、阿里、腾讯、DeepSeek、智谱、月之暗面、MiniMax 等）。决定放进题库页：复习「公司 × 频率」时可直接进入投递。
- **数据**：`companies` 新增 `career_url` / `career_note` 两列（`scripts/migrate_002_career_url.py`，IF NOT EXISTS 可重复执行）；`scripts/seed_career_urls.py` 以名称→别名顺序匹配既有 25 家公司幂等写入（微博合并「新浪/sina」别名），重跑 `更新 0, 一致 24`。只存官方域名入口，剥离第三方 UTM 追踪参数；2026-08-30 对 24 条 URL 全量存活探测（反爬拦截视同存活）。备注列只记结构性事实（网易游戏另走 campus.game.163.com、Google/微软/亚马逊岗位滚动上线需筛 China 等）。
- **API**：`GET /api/companies` 每项新增 `career_url` / `career_note`。
- **UI（题库页）**：公司瓷片下方新增「网申 ↗」直达（按钮与链接平级，避免 button 嵌套 a 的无效 HTML）；0 题但带网申入口的公司也展示（DeepSeek/MiniMax 等暂无题可先投递）；「按厂商」栏右侧提示行 + 悬浮说明：批次与岗位以官网最新公告为准、招满即止、谨防收费内推与保面骗局；选中公司后题列表头部显示「{公司} · 官方网申」。
- **边界**：面经页 / Dashboard 暂不重复展示（避免同字段多处维护）；入口链接会随厂商调整失效，更新走种子脚本而非手改数据库。

## 2026-08-30 续二十（题库工程能力维度：Python/Java/后端工程/项目深挖）

- **背景**：用户回看题库发现面经里真实出现的 Python/Java/后端基础与项目追问类问题（"遇到什么问题/模块为什么这样设计"）没有专门分类。口径红线（用户明确要求）：**贴合大模型应用场景，不是什么 Python/Java 题都要**。
- **词表扩展**：`tag_vocab.CANONICAL_TAGS` 与 `qa_extract.TAG_FAMILIES` 同步新增 4 个 canonical 标签（Python、Java、后端工程、项目深挖）+ 显式别名；抽取 prompt 写入场景口径：只标"大模型应用/Agent 开发岗真实会问的工程基础"（GIL/asyncio/流式生成器/并发服务化/缓存消息队列/网络 OS 常识），泛后端八股（Spring/JVM/SSM/泛型）不标。
- **存量回填**：`scripts/backfill_engineering_tags.py` 两阶段（SQL 关键词粗筛 774 候选 → LLM 按场景口径精判，项目追问类只召回 behavior/scenario kind）。只增不删、meta.eng_backfill_at 检查点幂等续跑、track 为空/未分类且命中工程标签时归入通用基础。结果：后端工程 290、项目深挖 107（含导入后增量 Python 112 / Java 48），Java 抽查全部是 LLM 集成/SSE/Agent 编排类场景题，泛 JVM 八股零误标。
- **补题**：新增 `interview-python` 源（taizilongxu/interview_python，17k star，无 license → STEMS_ONLY 仅取题干），导入 +133 题。
- **合规否决记录**：guoguo-tju/agent_java_offer（Java 后端+AI）为 CC BY-NC 4.0 → 按 sources.py 门禁 REFERENCE_ONLY 禁入；Snailclimb/JavaGuide（Apache-2.0 合规）主体为泛 Java 后端八股，**因不贴合大模型应用场景主动否决**；resumejob/interview-questions 内容已整体迁往商业站 osjobs.net，GitHub 仅剩链接目录，不作源。
- **前端**：题库页标签 chips 由"top 18"改为"计数 ≥20 全展示"，四个新分类直接露出（低频杂项仍截掉）。
