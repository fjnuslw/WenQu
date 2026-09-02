# IMP-G1-001：项目拷打仓库智能层 v2

> 状态：**Implementing（实现已收口；仅真实 embedding Provider 发布门待验证）**
> 创建日期：2026-09-02
> 父规范：[`docs/spec.md` F4 / G1](../spec.md#f4-项目拷打核心差异化)
> 研究依据：[`research/03-agent-harness与项目拷打技术.md`](../../research/03-agent-harness与项目拷打技术.md)、[`research/06-G1项目拷打竞品复核与设计.md`](../../research/06-G1项目拷打竞品复核与设计.md)
> 适用范围：G1 的仓库接入、结构理解、代码检索、Git 归属和 Agent 只读工具面
> 不改变：G1 v1 的 LLM 备课简报、简历声明质证、拷打会话、证据链报告；F3 双工具协议

## 0. 决策摘要

G1 v1 已经证明“上传/目录 → 备课 → 对照简历 → 现场读码 → 报告”主链路可用，但仓库理解仍依赖文件名/大小启发式和精确子串搜索。v2 增加一个与 Agent 解耦的 **Repository Intelligence** 层：

1. `RepositorySource` 统一本地目录、zip 和公共 HTTPS Git URL；源码获取与后续分析互不感知。
2. Tree-sitter 一次解析产出符号、结构和语法块；repo map 与语义索引消费同一份分析结果，避免重复解析。
3. repo map 采用 Aider 可借鉴的“定义/引用文件图 → personalized PageRank → 预算裁剪”，但以项目内窄接口重写，不引入 Aider 运行时。
4. cAST 风格语法块落独立 `repo_chunks` 表；embedding 经独立 Provider 网关生成，向量进入现有 pgvector `embeddings` 表。
5. Git 分析只读提交历史，输出贡献者、文件主要作者和候选人匹配结果，并明确历史采样范围。
6. Agent 只按项目能力动态获得 `get_repo_map / semantic_search / get_git_ownership`；每个工具最多两个业务参数，复杂状态留在 Harness/API 内。

**完成定义不是“代码路径存在”。** Tree-sitter 和 Git 必须通过真实仓库验收；pgvector 必须用真实数据库执行向量距离查询；未配置 embedding Provider 时必须诚实标记为不可用，现有 `search_code` 继续存在，但不得被称作语义检索。

## 1. 现状与范围校正

### 1.1 已有能力

- `apps/api/src/getoffer/grill/prep.py`：zip/本地目录接入、噪声过滤、启发式文件排序、分批 LLM 备课、简历声明对照。
- `apps/agents/src/tools/grill-repo.ts`：路径监狱内的 `list_files / read_file / search_code`。
- `Project + RepoArtifact`：可存 `tree / briefing / claims` 三类 checkpoint。
- `Embedding` 与 pgvector 扩展：数据库基础类型已存在，但没有代码块生产者或查询路径。

### 1.2 确认缺口

| 缺口 | 当前事实 | v2 目标 |
|---|---|---|
| 结构理解 | README/入口/文件大小启发式 | Tree-sitter 符号、签名、定义/引用图和 repo map |
| 代码分块 | LLM 批次按字符截断 | 语法边界优先、带 `文件:行号` 的稳定代码块 |
| 检索 | Agent 递归精确子串 | pgvector cosine 语义检索，结果回到源码锚点 |
| 仓库来源 | 本地目录 / zip | 增加公共 HTTPS Git URL，禁止本地协议和凭据注入 |
| 归属 | `.git` 被内容扫描排除且从未分析 | 独立只读 Git 分析，不把 `.git` 暴露给 Agent |
| Agent 上下文 | 首轮注入完整 LLM 简报 | 大产物按需工具读取，保持模型可见面窄 |

### 1.3 从原 G1 v2 条目移出的内容

- **Anki 导出不是本 Spec 的工作。** F6 已有 `GET /api/review/export.anki`；除非未来定义“项目拷打专属卡片协议”，不得再造第二套导出器。
- 主 Spec 中 F1 的“Meili + pgvector 混合题库搜索”是跨模块遗留项，不用 G1 代码块索引冒充。G1 的 embedding 网关可以复用，但 F1 的融合排序需另立 Spec。
- P1 多用户/UGC/LiveKit/职位聚合不属于当前本地 MVP 的 G1 v2。

## 2. 目标与非目标

### 2.1 目标

- Python、TypeScript/TSX、JavaScript/JSX、Java、Go、Rust 六类主流源码能够通过统一语言注册表解析。
- repo map 在固定仓库快照上确定性输出；重要文件排序由跨文件引用、特殊文件权重和符号定义共同决定。
- 每个代码块具有稳定 hash、语言、起止行、符号和分块策略；检索结果始终给出 `path:start-end`。
- embedding 模型、维度和代码快照身份可追踪；换模型或源码变化时不会混用旧向量。
- Git URL 获取不使用 shell 拼接，不接受 `file://`、SSH、本机/私网目标或 URL 内凭据。
- Git 归属给出贡献者和逐文件证据，候选人匹配只基于简历姓名/显式身份，不凭模型猜测。
- Agent 工具根据 artifact 能力动态注册；未配置语义层时不向模型展示 `semantic_search`。
- G1 v1 在解析器、Git 或 embedding 不可用时仍可备课，并明确显示降级项。

### 2.2 非目标

- 不实现 IDE 级精确调用图、类型推断或跨仓库依赖解析。
- 不声称 PageRank 等于“代码质量”；它只代表仓库内结构中心性和出题优先级。
- 不扫描 `.git` 对象内容，也不把 Git 写工具、bash 或任意 SQL 暴露给 Agent。
- 不自动抓取私有仓库凭据，不接受 token 写在 URL；私有仓库以后单独设计凭据托管。
- 不用哈希向量、关键词分数或 LLM 猜测冒充 semantic embedding。
- 本轮不引入 HNSW；单项目代码块规模先用 pgvector 精确 cosine 查询保证召回，达到容量阈值后另做索引评测。

## 3. 目标架构与模块边界

```text
local path ─┐
zip upload ─┼─► RepositorySource ─► RepoSnapshot ─► SyntaxAnalyzer (Tree-sitter, once)
https git ──┘          │                   │                 │
                      │                   │                 ├─► RepoMapBuilder ─► repomap artifact
                      │                   │                 └─► CodeChunker ─► repo_chunks
                      │                   │                                      │
                      │                   └─► existing LLM briefing              ▼
                      └─► GitOwnershipAnalyzer                         EmbeddingGateway
                                  │                                      │
                                  └─► ownership artifact                 └─► pgvector

API capability manifest ─► Agents Harness ─► dynamically selected read-only tools
```

| 模块 | 负责 | 不负责 |
|---|---|---|
| `grill/source.py` | 三种来源校验、解压/clone、来源元数据 | 解析代码、LLM、数据库 |
| `grill/syntax.py` | 语言识别、Tree-sitter 结构/符号/语法块 | 排名、向量、Git |
| `grill/repomap.py` | 定义/引用边、PageRank、预算渲染 | 再次读取/解析仓库 |
| `grill/chunks.py` | 规范化代码块、hash、源码行锚点 | embedding 请求 |
| `grill/embeddings.py` | Provider 协议、批处理、响应校验 | 相似度业务过滤 |
| `grill/retrieval.py` | chunk/向量持久化、pgvector 查询 | Agent Prompt |
| `grill/ownership.py` | 只读 Git 命令、历史范围、候选人匹配 | clone、简历解析 |
| `grill/prep.py` | 顺序编排、进度、checkpoint、失败归因 | 各模块内部算法 |

Tree-sitter 采用 `tree-sitter-language-pack` 的公开 `process()` / `ProcessConfig` 接口：其结构、符号和 syntax-aware chunks 来自同一遍解析。包版本锁在兼容主版本范围，依赖升级必须重新跑六语言 fixture。

repo map 的图算法参考 `references/aider/aider/repomap.py`（Apache-2.0）及其公开设计，但本项目只移植思想：

- 节点：源码文件。
- 边：文件 A 引用了文件 B 定义的符号，则 `A → B`，重复引用累加权重。
- personalization：README/入口/配置和现有收集重要度提供先验，但不能压过明显的跨文件中心性。
- 输出：按 rank 依次渲染 `文件 + 关键签名/符号 + 行号`，在字符预算内确定性截断。

## 4. 数据与接口

### 4.1 数据表与 artifact

新增 `repo_chunks`：

```text
id, project_id, path, language, start_line, end_line,
content, content_hash, symbols(JSON), meta(JSON)
```

- `Embedding(kind="repo_chunk", ref_id=repo_chunks.id)` 关联向量。
- 同一项目重建前删除旧 chunk 及其 embedding，防止悬挂和混用。
- `RepoArtifact.kind` 新增：
  - `repomap`：渲染文本、排名、解析覆盖率、解析器版本；
  - `semantic_index`：`ready/disabled/failed`、模型、维度、chunk/vector 数；
  - `ownership`：历史范围、贡献者、逐文件主要作者、候选人匹配；
  - `capabilities`：给 API/Agents 的窄能力清单。

### 4.2 配置

```text
GETOFFER_EMBEDDING__PROVIDER=disabled|openai_compatible
GETOFFER_EMBEDDING__BASE_URL=
GETOFFER_EMBEDDING__API_KEY=
GETOFFER_EMBEDDING__MODEL=
GETOFFER_EMBEDDING__DIMENSION=0
GETOFFER_EMBEDDING__TIMEOUT_SECONDS=45
```

- embedding 与聊天 LLM 配置分离；不得默认复用 DeepSeek key/model。
- `dimension=0` 表示首次响应确定维度，单批和已存索引内仍必须一致。
- API key 不进入 artifact、响应或日志。

### 4.3 HTTP API

```http
POST /api/grill/projects
  multipart: file | local_path | git_url（三选一）, name?, resume_id?

GET  /api/grill/projects/{id}
  + source, capabilities, repomap_summary, semantic_index, ownership_summary

GET  /api/grill/projects/{id}/map
POST /api/grill/projects/{id}/search       { "query": "...", "limit": 6 }
GET  /api/grill/projects/{id}/ownership?path=src/foo.py
```

`search` 成功响应必须包含 `mode="semantic"`、model、score、path、start/end line、content；语义层不可用返回可识别的业务错误，不静默转子串检索。

### 4.4 Agent 工具

| 工具 | 参数 | 注册条件 |
|---|---|---|
| `list_files` | `dir?` | 总是 |
| `read_file` | `path,start_line?,end_line?` | 总是 |
| `search_code` | `query` | 总是，精确定位符号仍有价值 |
| `get_repo_map` | 无 | `capabilities.repo_map=true` |
| `semantic_search` | `query,limit?` | `capabilities.semantic_search=true` |
| `get_git_ownership` | `path?` | `capabilities.git_ownership=true` |

模型无需填写 artifact id、向量模型、维度、项目 id、阈值或过滤表达式；这些由 Harness 闭包和 API 管理。

## 5. 流程、状态与失败策略

### 5.1 备课顺序

1. 获取/校验 RepositorySource，记录 source metadata。
2. 收集 RepoSnapshot；Tree-sitter 单遍分析。
3. 写 `repomap` checkpoint 与 `repo_chunks`。
4. embedding 配置存在时批量生成并写 pgvector；未配置则写 `semantic_index=disabled`。
5. 独立执行 Git 归属；无 `.git` 时写 `ownership.available=false`。
6. repo map 作为结构先验加入现有 LLM 备课输入；生成 briefing、claims。
7. 写 capabilities，项目进入 ready。

### 5.2 失败矩阵

| 故障 | 行为 |
|---|---|
| 单文件语言不支持/解析失败 | 记录 `parse_failures`，该文件沿用 v1 启发式；其他文件继续 |
| 所有源码均无法解析 | repo map 标记 degraded，v1 LLM 备课继续；不可声称结构覆盖完成 |
| embedding 未配置 | `semantic_index=disabled`，不注册 semantic tool |
| embedding 已配置但请求/维度校验失败 | 该阶段 `failed` 且项目备课失败；不留下半套新向量 |
| pgvector 写入失败 | 回滚本次 chunk/embedding 事务，项目失败并保留错误阶段 |
| 非 Git/zip 来源 | ownership `available=false, reason=no_history`，不影响其他阶段 |
| Git 命令超时/历史损坏 | ownership `available=false, reason=git_error`，v1 备课继续 |
| Git URL 非 HTTPS、带凭据或解析为私网 | 请求 422；不得调用 git |
| clone 中断 | 清理本次专用目标目录；Project 记录 failed |
| Agents 调 API 失败 | 工具错误可见；不得用模型记忆伪造 repo map/归属/语义结果 |

公共 Git 获取采用有界浅克隆但**不使用** `--filter=blob:none`：归属分析需要历史
`numstat`，blobless 仓库会在分析阶段触发不可控的懒加载。归属命令设置
`GIT_NO_LAZY_FETCH=1`，因此获取阶段结束后不会偷偷访问网络；历史对象不完整时按
`git_error` 显式降级。

## 6. 验收标准

### 6.1 Tree-sitter / repo map

- 六语言 fixture 均提取至少一个结构项、定义符号和合法行锚点。
- 人工构造 A→B→C 引用 fixture 中，核心定义文件排序高于孤立普通文件；同一快照重复运行输出字节一致。
- repo map 不超过配置预算的 115%，每条符号引用可回到真实文件行。
- 当前项目真实运行：受支持源码解析覆盖率 ≥90%（按进入 snapshot 的源码文件数），失败文件清单可见。

### 6.2 代码块 / pgvector

- 支持语言的函数/类不会在未超上限时被从中间切断；超大节点允许拆分并标注策略。
- chunk hash 在内容和锚点不变时稳定，源码改变后对应旧向量不会继续参与查询。
- fake Provider 单测覆盖批次顺序、维度不一致、数量不一致和密钥不泄露。
- 真实 PostgreSQL/pgvector smoke：写入至少 20 个真实代码块；自然语言查询 Top-5 至少命中人工标注相关文件；响应为 `mode=semantic`。

### 6.3 Git 来源 / 归属

- URL 校验覆盖 HTTPS 正例及 file/ssh/凭据/localhost/私网反例。
- 临时 Git fixture 至少两个作者、三个提交；贡献者 commit 数和逐文件主要作者与 `git log` 人工结果一致。
- 公共 Git URL 全流程可获取、记录 HEAD 和采样深度；clone 命令无 shell 插值。
- zip 项目明确显示“无 Git 历史”，不是空白或 0% 归属。

### 6.4 Agent / UI / 回归

- 三种 capability 组合的 Agent 单测证明工具动态注册，disabled 工具不出现在 schema。
- semantic tool 返回的每条命中都带可点击 `文件:行号`；ownership 工具不泄漏 URL 凭据或 API key。
- Web 可选择 Git URL，详情能看到 repo map/语义索引/Git 归属状态。
- API pytest + ruff、Agents test/typecheck/build、Web test/typecheck/build 全通过。
- 真实项目拷打审计中，面试官至少按需使用一次 repo map；当问题涉及实现位置时能用 semantic 或精确搜索后再 read_file 核证。

## 7. 推进计划表

> 最近更新：2026-09-02
> 更新规则：开始、完成、设计偏差或外部阻塞立即回写；`Verified` 必须附运行命令/基线文件。状态不得仅凭代码存在升级。

| 里程碑 | 状态 | 产物 | 完成判据 | 实际结果 / 调整 |
|---|---|---|---|---|
| M0 现状复核与范围校正 | ✅ Verified | 缺口证据、重复项清理、依赖核对 | 能区分 G1 v2、F1 混合搜索、F3 TTS 和 P1 | 确认 G1 仅有 v1 启发式/子串；Anki 已在 F6，移出本计划 |
| M1 架构与协议 | ✅ Verified | 本文、模块边界、数据/API/工具契约、失败矩阵 | 可独立指导实现且模型可见协议保持窄 | 采用 Source/Syntax/Map/Chunk/Embedding/Retrieval/Ownership 七模块；Agent 动态工具最多 0–2 参数 |
| M2 Tree-sitter 单遍分析与 repo map | ✅ Verified | `syntax.py`、`repomap.py`、六语言 fixture | §6.1 自动测试与当前仓库覆盖率达标 | 当前仓库 232 文件入快照，177/177 支持源码解析成功，370 chunks、3004 edges；repo map 5970 字符且重复运行确定性一致 |
| M3 代码块持久化与 pgvector 检索 | ✅ Completed | `RepoChunk`、embedding gateway、retrieval、API | §6.2 单测 + 真实 pgvector smoke | 真实 PostgreSQL/pgvector 写入 370 个真实代码块并执行 cosine 查询，目标 `retrieval.py` 位列 Top-5；Provider 批次/顺序/数量/维度/非数值/密钥不泄漏均有 fake 测试。当前 Provider=disabled，故**不得升级 Verified** |
| M4 Git URL 与归属分析 | ✅ Verified | `source.py` Git 通道、`ownership.py` | §6.3 安全/归属/公共仓库测试 | URL 反例、符号链接/目录联接边界与双作者三提交 fixture 通过；`pallets/itsdangerous` 经真实 HTTP API 到 ready：HEAD `672971d…`，15/15 解析、24 chunks、200 commits。按实测取消 blobless clone，验收临时目录已清理 |
| M5 API / Agent / Web 咬合 | ✅ Verified | capability manifest、动态工具、Git URL UI、状态卡 | §6.4 前三项 | API map/ownership 成功且 disabled search 返回 503；Agent 29 tests、Web 5 tests/typecheck/production build 通过；真实会话 `bdc242cb-…` 先调用 repo map，再读 5 个源码文件，未暴露 semantic tool |
| M6 全量回归与真实项目验收 | 🔄 In progress | 回归记录、repo-map/检索/归属基线、文档回填 | §6 全部通过才可 Verified | 基线见 [`g1-repository-intelligence-baseline.json`](../../apps/api/evals/g1-repository-intelligence-baseline.json)；API 121 tests + ruff、Agents 29 tests、Web 5 tests/production build、三服务健康。仅缺真实 embedding Provider 的自然语言 Top-5 发布门 |

状态含义：`⏳ Pending` 未开始；`🔄 In progress` 正在实施；`✅ Completed` 代码与隔离测试完成；`✅ Verified` 真实运行验收完成；`⛔ Blocked` 外部条件连续阻塞且已记录。

### 7.1 当前完成口径与下一动作

- **已经没有未实现的 G1 v2 代码模块。** Source/Syntax/Map/Chunk/Embedding/Retrieval/
  Ownership、API、Agent 工具与 Web 入口均已落地。
- **仍不能把整份 Spec 标成 Verified。** 当前 `.env` 明确为
  `GETOFFER_EMBEDDING__PROVIDER=disabled`；fixture 向量只证明 pgvector 存取与查询接线，
  不证明真实模型的代码语义质量。
- 配置 OpenAI-compatible embedding Provider 后，从仓库根执行
  `cd apps/api; ./.venv/Scripts/python.exe scripts/verify_g1_repository_intelligence.py --require-provider`；
  只有 `providerVerified=true` 且人工相关文件进入 Top-5，才把 M3/M6 与本文升级为 Verified。
- 真实拷打审计发现首轮用了 7 次工具、候选人可见回复 289 字，虽已正确先 map 后 read，
  但节奏偏重且突破 Prompt 的 120 字约束。它属于拷打交互/输出闸门，不属于仓库智能层；
  后续应另立改进 Spec，不在本项里用更多字段继续压模型。

## 8. 变更记录

- 2026-09-02：创建 Spec；完成现状审计、范围校正与官方依赖接口核对。
- 2026-09-02：M2 Verified——六类语言 fixture 与当前真实仓库均通过；修复“LLM 40 万字符预算误当结构索引预算”导致后部源码不可见的问题，结构层与 LLM 层预算正式分离。
- 2026-09-02：M3 Completed——真实 pgvector 接线通过，Provider release gate 因配置为 disabled 保持未通过，未用 fixture 冒充语义质量。
- 2026-09-02：M4 Verified——公共 Git 全流程首次暴露 blobless/history 懒加载阻塞；改为 200 提交有界完整对象浅克隆并禁止归属阶段懒加载，重跑通过。
- 2026-09-02：收口安全审查补齐 API 分析层的符号链接/Windows 目录联接拒绝；Agent 与 API 各自守住仓库真实路径边界。
- 2026-09-02：M5 Verified——API/Agent/Web 能力协商、动态工具、Git URL 与状态展示通过；同时把 F3 真实模型签名收窄到 `src/interview/` 领域文件，明确记录签名范围迁移，原实模指标未伪造重跑。
- 2026-09-02：M6 除 Provider gate 外完成；证据固化到 `apps/api/evals/g1-repository-intelligence-baseline.json`。
