# 交接文档：面经采集渠道扩充（牛客扩展 / 其他论坛 / 小红书人工通道）

> 交接对象：另一位 AI 执行者（Codex）。请**严格按本文档范围执行**，本文档未授权的文件一律不改动。
> 项目：问渠 WenQu（`D:\AI_Workspace\get_offer`，github.com/fjnuslw/WenQu，main 分支，提交者 fjnuslw）
> 撰写日期：2026-08-30。产品规格书：`docs/spec.md`（§3 知识工程 / §10 合规；续六为采集器落地记录）。数据渠道调研：`research/02-开源面经题库与数据渠道.md`。

---

## 0. 任务目标

扩充面经（experiences）数据来源，三条线：

1. **牛客网扩展**：现有采集器只采一个话题页且不分页——增加话题种子（算法/Agent/RAG/实习等多话题）与话题页分页采集。
2. **其他论坛**：评估并接入知乎、CSDN 面经汇总帖、linux.do RSS 等渠道（各自合规边界不同，见 §3）。
3. **小红书人工摘录通道**：小红书**禁止程序化爬取**（见红线），产品化路径是"人工摘录 + 导入"——新增手工导入端点与入口 UI，复用现有 LLM 抽取与入库管道。

## 1. 红线（违反任何一条即任务失败）

1. **小红书/抖音严禁爬虫**：不得编写任何请求 xiaohongshu.com / douyin.com 的自动化代码，不得引入/参考 MediaCrawler（其license亦禁用）。这是 spec §10 的法律边界（有刑事判例，见 research/02 §2.3）。小红书面经只能经"人工浏览 → 复制文本 → 手工导入"通道进入系统。
2. **robots 与限速**：一切自动采集必须走 `PoliteClient`（已实现 robots 门禁 + 渠道级最小间隔）。robots.txt 不可获取 = 拒绝采集（显式报错），**不得**默认放行、不得绕过。
3. **linux.do 的 Cloudflare 拦截不得绕过**：现有 `linux_do.py` 已实现但被 CF 403 拦截（显式失败是有意设计）。可以尝试其公开 RSS（`top.rss`）等**无需伪装**的通道；禁止伪造指纹、带登录态、注入 cookie 等绕过行为。
4. **知乎/CSDN/掘金只做低频公开页**：不登录、不破解、不高频。正文全文转载有版权风险——入库保留 `raw_text`（内部检索用）+ `url` 溯源即可，**不要**生成对外分发的内容页。
5. **禁正则解析 HTML**（spec §7）：HTML 一律 selectolax DOM（项目已依赖），JSON 用标准解析。
6. **禁静默 fallback**：上游失败/结构不符要抛类型化异常（`UpstreamError`/`ComplianceViolation`），不得 try-except 吞掉后返回空列表假装成功。
7. **幂等**：同帖重复采集必须 0 新增（content_hash 去重，已实现）；你的新渠道也必须走同一入口。
8. **不触碰范围外代码**（见 §6 禁区清单）。

## 2. 现有架构（必须复用，不得另起炉灶）

### 2.1 采集包（`apps/api/src/getoffer/ingest/collect/`）

| 文件 | 职责 | 你需要知道的 |
|---|---|---|
| `base.py` | `PostPreview`（url/title/meta/content）、`ChannelSpec`（slug/name/base_url/license_note/min_interval/fetch_posts） | 新渠道实现 `fetch_posts(client, max_posts) -> list[PostPreview]` 即可 |
| `polite.py` | `PoliteClient`：真实 UA + 每渠道最小间隔限速 + robots 门禁（urllib.robotparser）+ `GETOFFER_COLLECT_PROXY` 代理 | 直接实例化使用；robots 404=允许，其他非 200=拒绝采集 |
| `nowcoder.py` | 牛客话题页 SSR 采集（`SEED_SUBJECTS` 单话题，无分页）；详情页是 JS 壳拿不到全文——**话题页卡片预览就是游客上限**，抽取忠于预览 | 你要扩展的就是这里：多话题 + 分页 |
| `linux_do.py` | Discourse 游客 JSON（被 CF 拦，显式失败） | 可加 RSS 通道尝试，失败保持显式 |
| `__init__.py` | `CHANNELS` 注册表（dict[slug, ChannelSpec]）+ `get_channel()` | 新渠道在此注册，前端来源 tab 会自动出现 |
| `runner.py` | `collect_channel()`：拉取 → `experience_extract` LLM 结构化 → experiences/experience_items 幂等入库；`CompanyMatcher`（companies 表 name+alias 精确匹配，词表外报 `unmatched_companies` 不建行） | 不要改入库逻辑，渠道只管产出干净的 PostPreview |

### 2.2 抽取（`apps/api/src/getoffer/ingest/experience_extract.py`）

`ExperienceDraft`：`is_interview_experience / company / role / rounds / occurred_on / result / items[{question_text, note, followups}]`。prompt 已有规则：不编造、预览截断不补全、广告/资料帖拒收、**抽不出任何问题必须判非面经**。新渠道复用即可，勿改语义。

### 2.3 端点与配置

- 触发：`POST /api/ingest/collect/{slug}?max_posts=N`（内联执行，N≤30；返回 posts_seen/duplicates/skipped_non_experience/inserted/unmatched_companies）
- 读侧：`GET /api/experiences?company=&limit=&offset=`（web /experiences 页按来源 tab 展示，数据驱动）
- 代理：`apps/api/.env` 里 `GETOFFER_COLLECT_PROXY=http://127.0.0.1:7897`（本机直连这些域名 SSL 失败，实测需走 Clash；该文件已 gitignore，不要提交）
- 公司词表：`DEFAULT_COMPANIES`（25 家含别名，`ingest/company_tagging.py`）。面经里出现词表外公司（如"中科闻歌"）是**预期行为**（报 unmatched），不要为此建新公司行——扩充词表需用户授权，本次不做。

### 2.4 运行与验证环境

```bash
# 启动（Windows，PowerShell；或双击 start.bat）
powershell -File scripts/start.ps1     # 生产模式，源码变更自动重建；端口 23480(api)/23481(agents)/23482(web)

# 触发一次采集（经 web 同源代理；注意长任务勿在重建窗口期发请求）
curl -X POST "http://127.0.0.1:23482/api/ingest/collect/nowcoder?max_posts=5"

# 查看结果
curl "http://127.0.0.1:23482/api/experiences?limit=50" | python -m json.tool | head -50

# DB 直查（postgres 映射在 24432）
# psql 不一定装了；用 venv python：
cd apps/api && .venv/Scripts/python.exe -c "..."（参考 logs 里既有脚本风格，SQLAlchemy select experiences/experience_items）
```

日志在 `logs/api.*.log`。LLM 走 `GETOFFER_LLM__API_KEY`（DeepSeek），已在 `.env` 配好。

## 3. 三条线的具体要求

### 3.1 牛客扩展（主力渠道）

- **多话题种子**：现只有"大模型面经"话题（`8603768d1f224b6bbaa48c6b32880a1a`）。请在牛客站内人工确认 3-6 个相关话题页 URL（如 大模型/算法岗/Agent 开发/秋招 面 经 类话题），以 `creation/subject/{hash}` 形式加入 `SEED_SUBJECTS`。**人工确认方式**：浏览器搜 site:nowcoder.com 或站内搜索，复制话题页链接；不要猜 hash。
- **分页**：话题页 URL 带 `?type=new&order=...` 或滚动加载（先抓包确认分页参数，SSR 是否支持 page 参数以实际响应为准）。若 SSR 无分页，只采首页 feed 也可接受——在代码注释里写明实测结论，不要臆造参数。
- **反爬纪律**：保持 `min_interval=8s`；一次 run 的 max_posts ≤30。
- 已入库 13 条（含 网易/字节/B站/美团/讯飞 等），content_hash 会自动去重。

### 3.2 其他论坛

按"先评估后接入"顺序，每个渠道独立 ChannelSpec：

1. **CSDN 面经汇总帖**（research/02 §2.3 指出存在多平台汇总帖，如 blog.csdn.net 的大模型岗面经汇总，作者已从小红书/知乎/脉脉汇总去重）：CSDN 文章页是 SSR，selectolax 可解析正文。robots.txt 需先确认（blog.csdn.net 的 robots 对文章页的规则以实测为准；被禁就不做该站）。汇总帖特点：一帖含多家公司面经——`ExperienceDraft` 是单公司模型，一帖多公司时的处理策略：在渠道层按"公司段落"切分为多个 PostPreview（如可行），或抽取 prompt 支持输出多场（**推荐后者**：改 `experience_extract` 增加一个 `ExperienceBatch` 批量模型与独立函数，不破坏现有单帖路径）。
2. **知乎**：未登录限流明显，且转载授权问题——只做"问题页标题+高赞回答摘要"的**低频采集**或干脆不接（若实测限流不可用，在代码注释+交接总结里写明实测结论并跳过）。
3. **linux.do RSS**：`https://linux.do/top.rss` 与 `/latest.rss` 是 Discourse 公开 RSS，CF 通常放行 RSS（待实测）。若可用：解析 RSS XML（标准库 xml.etree，**不算 HTML 正则**）拿标题+链接+摘要，正文尝试 `/t/{id}.json`（若仍 CF 403 则只用 RSS 摘要，抽取忠于摘要）。仍被拦就保持显式失败并在总结里说明。
4. 其他你评估可行的**公开技术论坛**（如 V2EX？需 robots 实测）可自行判断，但每接入一个必须在交接总结里给出：robots 实测结论、频率设置理由、抽样数据质量。

### 3.3 小红书人工摘录通道（合规产品化）

不做任何爬虫。交付两件：

1. **手工导入端点**：`POST /api/ingest/collect/manual`（body：`{text: str, source_url: str|None, source_name: str="小红书人工摘录", occurred_on: str|None}`）→ 走**同一套** `experience_extract` → `collect_channel` 的入库段（幂等、公司匹配）。实现建议：在 `collect/` 包加 `manual.py`，复用 runner 的入库逻辑（可把 runner 的入库段抽成函数复用，改动最小化）。渠道固定 slug=`manual-xhs` 等，或直接写 experiences（走同 hasher）。
2. **web 入口**：`/experiences` 页顶部加"＋人工摘录"按钮 → 弹层（textarea 粘贴面经文本 + 可选原帖链接 + 渠道选择：小红书/知乎/脉脉/朋友分享）→ 调上述端点 → 刷新列表。UI 风格沿用现有（三级信息行、Badge、Card；参考该页现有代码）。此页**只加这一个入口**，不改其他。

## 4. 工程规范（本项目强制）

- Python 3.12 / FastAPI / SQLAlchemy async / pydantic v2；`ruff check`（line-length 110）与 `python -m py_compile` 必须过；B008（FastAPI Depends 默认参数）是全仓既有惯例可忽略。
- 提交：main 分支直提，commit message 中文、动宾结构（参考 `git log --oneline` 风格），提交者确保是 fjnuslw（仓库已配好，勿改 git config）。**先跑通 E2E 再提交**；每个渠道至少一笔独立 commit。
- spec 更新：只在 `docs/spec.md` 的增补记录末尾**追加**"续十八（面经渠道扩充）"一节（渠道清单/robots 实测结论/数据量/踩坑），不修改任何既有章节。
- 不新增重量级依赖（requests/httpx 已有；解析用 selectolax/标准库）。RSS 解析用 `xml.etree.ElementTree`。

## 5. 验收标准（逐条自检后在交接总结中给出证据）

1. 每个新渠道 `POST /api/ingest/collect/{slug}?max_posts=5` 返回 200 且 `inserted>0`（linux.do 若仍被拦：显式 502 + 明确错误信息也算验收通过，需贴响应）。
2. 幂等：同渠道同参数立即重跑 → `duplicates>0, inserted=0`。
3. 广告/资料帖被正确跳过（`skipped_non_experience>0` 的样例）。
4. `/experiences` 页出现新来源 tab，问题树渲染正常（浏览器或 curl HTML 验证）。
5. robots 拒绝路径：人为请求一个 robots 禁止的 URL（如 nowcoder /search）→ 返回 `compliance_violation` 错误而非静默。
6. 小红书通道：curl 导入一段真实小红书面经文本 → 入库 → 页面可见，来源显示人工摘录渠道。
7. 全程未触碰 §6 禁区文件（git diff 自查）。

## 6. 禁区（不得改动）

- `apps/agents/**`（面试/拷打/答题 agent 与语音——全部已完成并实测，任何改动都会破坏行为契约）
- `apps/web` 中除 `/experiences` 页新增"人工摘录"入口外的**一切文件**（尤其 chat-room.tsx、grilling、review、resume、dashboard、bank）
- `apps/api` 中除 `ingest/collect/**`、`ingest/experience_extract.py`（仅新增批量模型，不改既有函数语义）、`api/routers/ingest.py`（新增 manual 端点）、`api/routers/experiences.py`（若人工导入需要，只加不改）外的模块；**models.py 不得加表**（experiences 体系已够用，`source` 表复用）
- `scripts/**`（启停脚本已稳定，端口策略不动）、`docker-compose.yml`、`docs/spec.md` 既有章节（只允许追加续十八）、`research/**`、`README.md`
- 端口（23480-23482/24432/27700/26379）与所有 `.env` 既有键

## 7. 交接总结要求（任务完成时输出）

在仓库根新建 `docs/handoff-采集扩充-总结.md`：渠道清单（slug/来源/robots 结论/min_interval）、每渠道数据量与质量抽样（公司识别率、追问链数量）、E2E 证据（命令+响应摘录）、踩坑与遗留（如 CF 仍拦、知乎限流跳过）、git log 清单。最后 push 到 main。

---

*本项目的编码原则（spec §7）：禁正则硬编码解析、禁 fallback 堆砌、失败显式、幂等管道。执行中有歧义时，选择更保守（更少数据、更显式失败）的那个。*
