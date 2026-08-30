# 面经采集扩充交接总结

> 完成日期：2026-08-30
> 范围：牛客多话题、CSDN 公开页、linux.do RSS 合规尝试、小红书等人工摘录通道。

## 1. 渠道清单与合规结论

| slug | 来源/入口 | robots 与上游实测 | min_interval | 当前结论 |
|---|---|---|---:|---|
| `nowcoder` | 牛客 4 个 AI/Agent/实习面经话题 | subject/feed 允许；`/search` 明确 Disallow | 8s | 可用；各话题只采最新 SSR 首页 |
| `csdn` | CSDN 3 篇已审核大模型面经 | robots 允许文章路径；`#content_views` SSR 可解析 | 12s | 可用；仅内部检索 + 原帖溯源 |
| `linux-do` | `top.rss` / `latest.rss` | robots 门禁可判且允许请求；两个 feed 均遭 CF 403 | 10s | 显式 502；不绕过，改走人工摘录 |
| `manual-xhs` | 小红书人工复制粘贴 | 不发任何网络请求 | N/A | 可用 |
| `manual-zhihu` | 知乎人工复制粘贴 | 不发任何网络请求 | N/A | 可用（首次导入时建 Source） |
| `manual-maimai` | 脉脉人工复制粘贴 | 不发任何网络请求 | N/A | 可用（首次导入时建 Source） |
| `manual-friend` | 朋友分享文本 | 不发任何网络请求 | N/A | 可用；广告样例被拒收 |

未接入知乎自动采集：对公开回答 URL 走 `PoliteClient` 实测，直接得到 `compliance_violation`，robots 禁止该路径。全程没有编写或执行任何小红书/抖音请求代码。

### 牛客种子（均由站内/`site:` 搜索结果人工打开确认）

1. 大模型面经：`8603768d1f224b6bbaa48c6b32880a1a`
2. Agent 面经：`bdbbe1dc5f2d4396b09a261d2871ad01`
3. 面试官拷打 AI 项目都会问什么：`64d29ae024874248b2f8e10c88d41f7d`
4. 实习面试记录：`b8fb04662b3e4a3698d028cff4f643f2`

分页实测：同一 Agent 面经话题的 `?type=new&page=1/2/3` 均返回 16 个帖子 URL，集合完全相同，故 SSR 没有有效翻页。实现没有猜内部滚动 API，而是公平采四个首页；HTTP 200 空壳只做一次受限重试，仍异常就抛类型化错误。

## 2. 数据量与质量抽样

SQL 统计口径：按 `sources.slug` 聚合 `experiences`，公司识别率为 `company_id IS NOT NULL`，追问为 `experience_items.parent_id IS NOT NULL`。

| 来源 | 面经数 | 公司匹配 | 主问题 | 追问链节点 | 抽样质量 |
|---|---:|---:|---:|---:|---|
| 牛客 | 16 | 10/16（62.5%） | 164 | 10 | 新增样例覆盖字节 AI Agent、Agent 项目深挖、虾皮 Agent；虾皮不在词表，按约束只报 unmatched |
| CSDN | 3 | 2/3（66.7%） | 90 | 0 | 字节/阿里淘天/美团三篇均抽出具体问题；`阿里淘天` 未精确命中词表，不擅自建公司 |
| 小红书人工摘录 | 1 | 1/1（100%） | 3 | 1 | 字节大模型应用一面；日期 `2026-08-28`、RAG 题及“混合检索权重”追问正常渲染 |
| 朋友分享广告样例 | 0 | 0 | 0 | 0 | 明确资料领取/引流文本，`skipped_non_experience=1` |

总计 20 条面经。CSDN 三篇都触及单帖 schema 的 30 题上限；这是忠实截断，不扩写文章之外内容。若后续要接真正的“多家公司合一”长帖，再新增批量模型；本轮选择单公司种子，避免在没有稳定公司段落边界时误拆。

## 3. E2E 证据

### 牛客首次与幂等重跑

```text
POST /api/ingest/collect/nowcoder?max_posts=5
{"channel":"nowcoder","posts_seen":5,"duplicates":1,
 "skipped_non_experience":1,"inserted":3,"unmatched_companies":["虾皮"]}

立即重跑
{"channel":"nowcoder","posts_seen":5,"duplicates":4,
 "skipped_non_experience":1,"inserted":0,"unmatched_companies":[]}
```

重复帖 4 条直接命中哈希；另一条资料/非面经仍忠实走 LLM 拒收，所以重跑仍计入 `skipped_non_experience`。

### CSDN 首次与幂等重跑

```text
POST /api/ingest/collect/csdn?max_posts=3
{"channel":"csdn","posts_seen":3,"duplicates":0,
 "skipped_non_experience":0,"inserted":3,"unmatched_companies":["阿里淘天"]}

立即重跑
{"channel":"csdn","posts_seen":3,"duplicates":3,
 "skipped_non_experience":0,"inserted":0,"unmatched_companies":[]}
```

### linux.do Cloudflare 显式失败

```text
HTTP/1.1 502 Bad Gateway
{"error":{"code":"upstream_error",
 "message":"linux.do 的 top.rss 与 latest.rss 均被 Cloudflare 挑战页拦截；不绕过防护，请改走人工摘录",
 "details":{"feeds":[{"url":"https://linux.do/top.rss","status":403},
                       {"url":"https://linux.do/latest.rss","status":403}]}}}
```

本地 XML fixture 已验证 RSS `channel/item/title/link/description` 标准解析，以及 description HTML 经 selectolax 转纯文本。

### 人工摘录、幂等与广告拒收

```text
POST /api/ingest/collect/manual  # 小红书人工摘录，3 题 + 1 追问
{"channel":"manual-xhs","posts_seen":1,"duplicates":0,
 "skipped_non_experience":0,"inserted":1,"unmatched_companies":[]}

同 body 经 web 同源代理立即重跑
{"channel":"manual-xhs","posts_seen":1,"duplicates":1,
 "skipped_non_experience":0,"inserted":0,"unmatched_companies":[]}

朋友分享广告文本
{"channel":"manual-friend","posts_seen":1,"duplicates":0,
 "skipped_non_experience":1,"inserted":0,"unmatched_companies":[]}
```

浏览器实测 `/experiences`：显示来源 tab `牛客 16 / CSDN 3 / 小红书人工摘录 1`；点击“人工摘录”可见文本、四渠道、日期、URL 字段和“不访问原帖”说明；筛选小红书后仅显示 1 条，日期、3 个根问题与 1 个追问正常。

### robots 拒绝路径

```text
PoliteClient.get("https://www.nowcoder.com/search")
{"code":"compliance_violation",
 "message":"robots.txt 禁止采集该路径: https://www.nowcoder.com/search"}
```

知乎公开回答路径同样被 robots 明确拒绝，因此没有注册自动 ChannelSpec。

## 4. 工程检查

```text
ruff check --ignore B008 ...                         All checks passed
python -m py_compile <本轮 Python 文件>             passed
pytest                                              11 passed
npx tsc --noEmit --incremental false                passed
npm run build                                       passed
```

Next production build 首次在受限沙箱的 TypeScript worker 处报 `spawn EPERM`；相同构建获准在沙箱外执行后完整通过（10/10 静态页），属于进程权限而非代码错误。

## 5. 踩坑与遗留

- 牛客 `page` 是无效 SSR 参数；若未来站点提供公开分页链接，必须重新抓包/实测并继续经过 PoliteClient，不能复用猜测接口。
- 牛客偶发 200 空壳；当前只允许一次同 URL、同 UA、同 8 秒门禁的重试，失败显式上抛。
- linux.do RSS 与 JSON 当前均受 CF；不要加入 cookie、登录态、浏览器指纹或挑战绕过。可用路径仍是人工摘录。
- 知乎 robots 当前禁止目标回答路径；规则变化前不接自动采集。
- CSDN 的 `阿里淘天` 与牛客的 `虾皮` 未命中公司词表是预期行为；本次没有改公司表。
- 人工来源中的 URL 只存储作溯源，不会被后端访问；`manual://...` Source base URL 进一步避免误用。
- 工作区原有 `apps/web/tsconfig.tsbuildinfo` 未提交改动始终未暂存、未覆盖。

## 6. Git 提交清单

```text
1077968 扩充牛客面经多话题采集
c4a6d39 接入CSDN公开面经采集
dfb2eec 扩展linux.do公开RSS采集
b8b4ceb 新增面经人工摘录闭环
```

文档续十八与本总结由最后一笔文档提交承载。所有功能提交均在 `main`，提交者沿用仓库配置 `fjnuslw`。
