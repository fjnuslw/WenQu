# 问渠 WenQu

> 问渠那得清如许，为有源头活水来 —— 面经知识库是源头活水，面试是问渠。
>
> 大模型应用 / AI Agent 开发方向求职平台：**面经知识库 · 厂商题库 · AI 考官模拟面试 · 项目读码拷打**。

架构按完整产品设计（spec v0.3），按垂直切片交付。**K1 / I1 / G1 / L1 全线跑通**：题库 22,000+ 题（11 开源源 + LeetCode Hot100，license 门禁）→ 简历押题组卷模拟面试 → 评分报告失分点回流 SM-2 复习 → 项目拷打（读码备课 + 架构拷打 + 证据链报告）。

## 功能全景

| 模块 | 入口 | 说明 |
|---|---|---|
| 题库 | `/bank` | 公司 × 岗位 × 频率榜；每题可唤起**答题助手**（max 档思考流 + 联网核实，思考过程右栏实时可见） |
| 面经 | `/experiences` | 牛客话题页 SSR 合规采集（限速 + robots 门禁）→ LLM 结构化「公司-岗位-轮次-问题树」，按来源分类 |
| 模拟面试 | `/interview` | 简历押题 × 公司面经追问 × 频率榜 LLM 定卷 → 题单驱动面试 → 评分报告（证据链）|
| 项目拷打 | `/grilling` | 上传项目目录/zip → 异步备课（架构向拷打题 + 简历声明质证）→ 拷打官真读码深挖，`文件:行号` 点击核证 |
| 简历工作台 | `/resume` | PDF 解析画像 + JD 匹配度（匹配/缺口/建议）+ 声明质证底稿 |
| 复习队列 | `/review` | 失分点自动回流 SM-2，掌握度统计 + 一键导出 Anki |

## 一键运行（Windows）

| 双击 | 作用 |
|---|---|
| `setup.bat` | 环境准备：工具链检查、uv 虚拟环境、npm 依赖、从 example 生成 .env（已有则不动） |
| `start.bat` | 启动全部：docker 基础设施 → api → agents → web（生产模式默认，源码变更自动重建）；端口清障+健康检查 |
| `status.bat` | 各服务 pid/端口/健康 + docker 容器 + 密钥是否填写 |
| `stop.bat` | 停止三个应用服务（不动 docker）；`powershell -File scripts\stop.ps1 -Docker` 连基础设施一起停 |

**首次启动前**：编辑 `apps\api\.env` 填 `GETOFFER_LLM__API_KEY`，编辑 `apps\agents\.env` 填 `DEEPSEEK_API_KEY`（不填也能启动，LLM 相关功能显式报 503）。

## 模型与端口

| 项 | 值 |
|---|---|
| 模型 | `deepseek-v4-flash-vision-exp`（实验模型，API 校验小写 id；不在 pi-ai 0.84.3 静态目录中——`apps/agents/src/pi.ts` 用 `createProvider` 显式注册派生条目） |
| web / api / agents | 23482 / 23480 / 23481（冷门段，启动前探测占用、冲突自动顺延，start.ps1 会把实际端口回写 `apps/web/.env.local`） |
| postgres / meilisearch / redis | 24432 / 27700 / 26379（docker 端口映射） |

## 总体架构

```
                ┌────────────────── 浏览器 ──────────────────┐
                │  Next.js 16 UI（暗色优先/命令面板/证据链报告）  │
                └────────┬────────────────────┬─────────────┘
                 REST /api│              SSE/REST│
                 ┌────────┴─────────┐   ┌────────┴──────────────────┐
                 │ apps/api FastAPI │   │ apps/agents Node + pi 运行时│
                 │ 知识工程管道        │◄─►│ F3 面试 agent（状态机+追问） │
                 │ 题库/面经/检索/复习  │内部│ F4 拷打 agent（只读工具面）  │
                 │ 评测/简历/仓库分析   │   │ 会话 JSONL append-only     │
                 └─┬─────┬──────┬───┘   └────────┬─────────────────┘
        ┌──────────┴─┐ ┌─┴─────┐ ┌┴─────┐    OpenAI 兼容│
        │ Postgres   │ │ Meili │ │Redis │      ┌────────┴──────┐
        │ + pgvector │ │ (CJK) │ │(arq) │      │ DeepSeek      │
        └────────────┘ └───────┘ └──────┘      └───────────────┘
```

- `apps/agents` 直接依赖 **@earendil-works/pi-agent-core / pi-ai 0.84.3**（MIT）；自研部分是阶段状态机、4 级提示追问阶梯与 SSE 桥接；pi 接触面收敛在 `src/pi.ts`。
- `apps/api` 知识管道：markdown→AST（mistune）、HTML→DOM（selectolax）、代码→tree-sitter（G1）；**禁正则硬编码、禁 fallback 堆砌**（spec §7）。
- 参考源码在 `references/`（pi-mono、deepwiki-open、gitingest、repomix、The-Interview-Mentor、aider repomap.py、DeepSeek Harness 架构文档），复用地图见 spec §8。

## 手动运行（等价于脚本内部行为）

```bash
docker compose up -d
# api
cd apps/api && .venv/Scripts/python -m uvicorn getoffer.api.main:create_app --factory --port 23480
# agents
cd apps/agents && npm run dev          # :23481
# web
cd apps/web && npm run dev -- -p 23482
```

## 文档导航

| 文档 | 内容 |
|---|---|
| [docs/spec.md](docs/spec.md) | **Spec v0.3**：完整架构、F1–F6 功能规格、题库丰富度计划、WebUI 设计规范、工程原则、源码复用地图、里程碑（含阶段状态） |
| [research/01–05](research/) | 竞品 / 数据渠道与合规 / agent harness 技术 / 简历画像与考点映射 / 补充功能与差异化 |

## 验证状态（2026-08-29）

| 部分 | 验证 |
|---|---|
| K1 导入管道 | 全链实测：clone(代理)→AST→LLM 抽取(思考关闭)→去重→Postgres→Meili；增量重跑幂等（source_files 收敛记账） |
| 题库数据 | **1500+ 题且持续增长**（`scripts/import_source.py --all` 后台灌库）；LeetCode 手撕题 101 题已入库 |
| 厂商分类 | 24 厂商种子 + AI 推断标注（592+ 条 question_companies），`company=字节跳动` 等筛选可用；分类守护进程持续标注新题 |
| apps/api | `pytest 11/11` |
| apps/agents · web | `tsc --noEmit` 零错误 |
| 全栈 | stop/start 幂等循环 + 健康检查 + license 门禁 + 检索冒烟全绿 |

## 常用数据操作

```bash
cd apps/api
# 全源灌库（后台数小时，断点续跑幂等）
.venv/Scripts/python scripts/import_source.py --all --batch 12
# 单源
.venv/Scripts/python scripts/import_source.py --slug agent-guide
# 厂商标注（循环调用直到 classified=0）
curl -X POST "http://127.0.0.1:23480/api/ingest/classify-companies?limit=25"
# 检索索引重建 / LeetCode 种子（幂等）
curl -X POST http://127.0.0.1:23480/api/ingest/reindex
.venv/Scripts/python scripts/seed_leetcode.py
```

## 里程碑

P0 基座 ✅ → **K1 知识冷启动 ✅（2026-08-29）** → **I1 面试循环（当前阶段）** → G1 项目拷打 → L1 学习闭环 → P1 公开化。详见 spec §9。
