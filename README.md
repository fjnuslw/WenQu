# 问渠 WenQu

> 问渠那得清如许，为有源头活水来。

**大模型应用 / AI Agent 方向的求职备战平台**——面经知识库、厂商题库、AI 考官模拟面试、**项目读码拷打**、间隔复习闭环，全部本地部署、数据留在你自己机器上。

[![license](https://img.shields.io/badge/license-MIT-green)]() [![deploy](https://img.shields.io/badge/deploy-%E6%9C%AC%E5%9C%B0%E5%8D%95%E7%94%A8%E6%88%B7-purple)]() [![python](https://img.shields.io/badge/python-%E2%89%A53.12-blue)]() [![node](https://img.shields.io/badge/node-22-blue)]()

---

## 它解决什么问题

求职大模型应用岗的真实痛点：八股题库烂大街，但**面试官真正拷打的是你简历上的项目**——「这个模块怎么实现的？为什么不用 X 方案？为什么没做 Y？」。市面上少有产品能读懂你的仓库再针对你提问。

问渠补的就是这块：把「面经 → 题库 → 模拟面试 → 项目拷打 → 失分复习」串成一个闭环，且每一环都能追溯到原始证据。

| 能力 | 说明 |
|---|---|
| 🗂️ **题库 22,812 题** | 11 个开源源（License 门禁）+ LeetCode Hot100；支持公司 × 岗位 × 频率榜三维筛选 |
| 📰 **真实面经 503 条** | 公开页面合规采集 → LLM 结构化为「公司-岗位-轮次-问题树」 |
| 🎯 **AI 考官模拟面试** | 简历考点 × 公司面经追问 × 频率榜 → LLM 定卷 → 题单驱动的状态机面试 |
| ⚔️ **项目读码拷打**（核心差异位） | 上传项目目录 → AI 备课 → 拷打官**真读码**深挖，回答对照代码实时质证 |
| 🔗 **证据链报告** | 每条评分结论挂**你的原话 + `文件:行号`**，点击即可回看现场 |
| 🔁 **间隔复习闭环** | 失分点自动回流 SM-2 → 标签掌握度统计 → 一键导出 Anki |
| 🗺️ **五条学习路径** | 109 个节点 / 141 条已核验资源 / 161 个资源锚点，可订阅、可勾选进度 |

## 截图

**项目拷打**：拷打官对照真实代码提问（右栏实时思考过程 + 项目文件树），点击 `文件:行号` 直接在侧栏定位到那一行。

![拷打会话](docs/screenshots/grill-session.png)

**证据链报告**：每个维度、每条失分点都挂候选人原话与代码位置，失分点可一键回流复习队列。

![证据链报告](docs/screenshots/evidence-report.png)

| | |
|---|---|
| ![工作台](docs/screenshots/dashboard.png) | ![题库](docs/screenshots/bank.png) |
| **工作台**：真实统计 + 学习路径进度 | **题库**：厂商瓷片 × 岗位大类 × 问助手 |
| ![面经](docs/screenshots/experiences.png) | ![项目备课](docs/screenshots/grilling.png) |
| **面经**：按来源分类 + 问题树 | **项目拷打**：目录选择 → 异步备课 → 随时再开一场 |
| ![复习队列](docs/screenshots/review.png) | ![JD 匹配](docs/screenshots/resume-jd.png) |
| **复习队列**：SM-2 + 掌握度 + Anki 导出 | **简历工作台**：画像 + JD 匹配度（匹配/缺口/建议） |

---

## 环境要求

| 依赖 | 版本 | 说明 |
|---|---|---|
| **Docker Desktop** | 任意近期版本 | 跑 PostgreSQL / MeiliSearch / Redis 三件套 |
| **Node.js** | 22+ | web 与 agents 两个服务 |
| **Python** | 3.12+ | api 服务 |
| **uv** | 最新版 | Python 依赖管理，`setup.bat` 会自动安装 |
| **DeepSeek API Key** | — | 全部 LLM 能力依赖它，[在此申请](https://platform.deepseek.com/) |

> **平台说明**：一键脚本（`setup.bat` / `start.bat` / `stop.bat` / `status.bat`）目前**仅支持 Windows**（PowerShell）。macOS / Linux 用户可按「手动部署」一节的步骤自行起服务。

## 快速开始

```bat
1. git clone https://github.com/fjnuslw/WenQu.git
   cd WenQu

2. 双击 setup.bat
   :: 自动检查工具链、安装依赖、生成 .env 样例

3. 填入你的 API Key（两个文件都要填）
   apps/api/.env      → GETOFFER_LLM__API_KEY=sk-xxxxxx
   apps/agents/.env   → DEEPSEEK_API_KEY=sk-xxxxxx

4. 双击 start.bat
   :: 拉起 docker 基础设施 + 三个服务，并等待健康检查就绪

5. 打开 http://127.0.0.1:23482
```

首次启动会初始化数据库表结构（约 10 秒）。**题库与面经需要你自己导入**，仓库不含任何数据快照——导入方式见「数据从哪来」一节。

### 手动部署（macOS / Linux）

```bash
# 1. 基础设施
docker compose up -d

# 2. api
cd apps/api && uv sync && uv run uvicorn getoffer.api.main:create_app --factory --port 23480

# 3. agents
cd apps/agents && npm install && npm run dev

# 4. web
cd apps/web && npm install && npm run dev
```

## 配置说明

配置集中在两个 `.env`（由 `setup.bat` 从 `.env.example` 生成）。**绝大多数保持默认即可**，必填的只有 API Key。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `GETOFFER_LLM__API_KEY` | 空 | **必填**。留空时服务照常启动，但所有 LLM 功能抛 `NotConfigured` |
| `DEEPSEEK_API_KEY` | 空 | **必填**（agents 侧）。与上者填同一个 key 即可 |
| `GETOFFER_LLM__MODEL` | `deepseek-v4-flash-vision-exp` | 换模型改这里（需 OpenAI 兼容接口） |
| `GETOFFER_DATABASE_URL` | `...localhost:24432/getoffer` | 改端口或换库时调整 |
| `GETOFFER_TTS__PROVIDER` | `disabled` | 语音朗读默认关闭，配置后启用 |
| `GETOFFER_GIT_PROXY` / `GETOFFER_COLLECT_PROXY` | 空 | 网络受限环境可填代理 |

## 日常使用

| 操作 | 命令 / 动作 |
|---|---|
| 启动 | 双击 `start.bat` |
| 停止 | 双击 `stop.bat` |
| 查看状态 | 双击 `status.bat`（三服务健康检查 + 端口占用） |
| 重启 | `stop.bat` → `start.bat` |
| 看日志 | `logs/api.err.log`、`logs/web.out.log`、`logs/agents.err.log` |

**改了前端代码记得重新构建**——web 走生产模式（`next build` + `next start`），改完源码不重新构建，页面不会变。`start.bat` 会自动构建，但如果你只想单独重建：

```bat
cd apps/web && npx next build
```

## 常见问题

| 症状 | 原因与处理 |
|---|---|
| `start.bat` 报端口被占用 | 脚本会自动清理本项目端口上的遗留进程；若仍失败，手动 `stop.bat` 后再启，或检查是否有其他程序占用 23480-23482 / 24432 / 27700 / 26379 |
| Docker 相关报错 | 确认 Docker Desktop 已启动并处于 running 状态，`docker compose ps` 应看到 3 个容器 |
| 服务起来了但面试 / 题库问答报 `NotConfigured` | API Key 没填或填错，检查两个 `.env` 并重启 |
| 改了前端代码页面没变 | 生产模式需重新构建，见「日常使用」 |
| `python` 版本不对 | 需 3.12+；`setup.bat` 用 uv 装依赖，会按 `pyproject.toml` 选版本 |
| 数据库连不上 | 先确认 docker 三件套在跑：`docker compose ps` |
| 想彻底重来 | `stop.bat` → 删除 docker 数据卷 → `start.bat`（会重建空库，再重新导入数据） |

## 数据从哪来

**仓库不含任何数据快照**，`data/` 与数据库都不进 Git。所有数据由你自己导入，导入器带幂等设计，可反复重跑：

```bat
:: 题库：从 11 个开源源导入（License 门禁自动生效）
cd apps/api && uv run python scripts/import_source.py --all

:: 面经：见 docs/spec.md §10 的采集通道说明
:: 运维脚本（按需运行）
uv run python scripts/backfill_company_freq.py   :: 用面经校准公司频率榜
uv run python scripts/recheck_pins.py            :: 复检学习路径的 161 个资源锚点
uv run python scripts/verify_f3_interview.py     :: 统计模拟面试的追问链产出
```

**License 门禁是硬性的**：GPL / AGPL / NC 协议的内容**不入库**，只作站外引用；无 License 的源仅提取题干、答案自写。当前库内零 GPL 内容。

## 项目结构

```
apps/
  api/      FastAPI：知识管道（采集/抽取/检索）、组卷、报告、复习、统计
  agents/   Node + pi 运行时：面试 / 拷打 / 答题三个 agent
  web/      Next.js 16：全部前端页面
docs/       规格说明书（spec.md）与截图
research/   竞品调研、数据渠道、agent harness 技术调研
scripts/    一键启停脚本（Windows PowerShell）
```

## 架构

```
        ┌────────────── 浏览器（Next.js 16，暗色优先）──────────────┐
        │  题库/面经/面试/拷打/简历/复习 —— 同源代理（SSE 逐块流式）    │
        └──────┬─────────────────────────────┬────────────────────┘
        REST /api│                        SSE /agents│
   ┌────────────┴───────────┐      ┌───────────────┴────────────────┐
   │ apps/api · FastAPI      │      │ apps/agents · Node + pi 运行时   │
   │ 知识管道（采集/抽取/检索）│ 内部  │ 面试 agent（状态机 + 追问阶梯）   │
   │ 组卷/报告/复习/统计      │◄────►│ 拷打 agent（只读工具面 + 路径监狱）│
   └──┬──────┬──────┬───────┘      │ 答题 agent（web_search + 思考流） │
   Postgres  Meili  Redis           └───────────────┬────────────────┘
   +pgvector (CJK) (arq)                    OpenAI 兼容│
                                              ┌───────┴────────┐
                                              │  DeepSeek API   │
                                              └────────────────┘
```

技术选型与工程原则（禁正则硬编码解析、禁静默 fallback、append-only JSONL 会话、类型化错误族、幂等管道）见 **[docs/spec.md](docs/spec.md)**；竞品与数据渠道调研见 **[research/](research/)**。

## Roadmap

- [x] K1 题库与面经知识核心（22,812 题 + 合规采集管道）
- [x] I1 模拟面试循环（简历押题组卷 → 评分报告 → 失分回流）
- [x] G1 项目拷打 v1（备课 / 只读工具面 / 证据链报告）
- [x] L1 学习闭环（SM-2 / 掌握度 / Anki / JD 匹配）
- [x] 面经 → 公司频率榜事实校准（可追溯到具体面经条目）
- [x] 语音朗读（TTS，默认关闭可配置启用）
- [x] F7 学习路径（五条线 · 进度订阅 · 锚点复检自动化）
- [ ] G1 v2：tree-sitter repo map / pgvector 语义检索 / git 归属分析
- [ ] 长面验收实测（30 分钟 ≥8 条追问链，脚本已就绪待跑）

## 复用与致谢

Agent 运行时复用 [pi-agent-core / pi-ai](https://github.com/earendil-works/pi)（MIT）；架构思想参考 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（插件化）、[deepwiki-open](https://github.com/AsyncFuncAI/deepwiki-open)（repo 理解）、[The-Interview-Mentor](https://github.com/ps06756/The-Interview-Mentor)（阶段机 + rubric）、aider repomap（Apache-2.0）。题库源遵守各自 License，详见 spec §10。

---

## License 与免责声明

代码使用 **MIT**，详见 [LICENSE](LICENSE)。

使用本项目前请知悉：

- **本项目为个人学习用途设计，形态是本地单用户**，没有多租户、认证与限流，请勿直接部署为公开服务。
- **数据需自行导入**：仓库不分发任何第三方内容。项目自带的采集器在 `robots` 与公开范围内低频工作，但你导入的数据，其合规责任由你承担；面经类内容仅供个人学习，对外分发前请自行评估版权与平台条款风险。
- **API Key 是你自己的**：`.env` 已被 Git 忽略，请勿将填好 Key 的 `.env` 提交或分享。
- **AI 输出不保证准确**：面试评分、押题、拷打结论均由 LLM 生成，请批判性看待，重要决策不要依赖单一模型输出。
