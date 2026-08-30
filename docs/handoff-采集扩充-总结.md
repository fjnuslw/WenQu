# 面经采集扩充交接总结

> 完成日期：2026-08-30
> 范围：牛客多话题、CSDN 公开页、linux.do RSS 合规尝试、小红书/抖音等人工摘录通道。

## 1. 渠道清单与合规结论

| slug | 来源/入口 | robots 与上游实测 | min_interval | 当前结论 |
|---|---|---|---:|---|
| `nowcoder` | 牛客 4 个 AI/Agent/实习面经话题 | subject/feed 允许；`/search` 明确 Disallow | 8s | 可用；各话题只采最新 SSR 首页 |
| `csdn` | CSDN 3 篇已审核大模型面经 | robots 允许文章路径；`#content_views` SSR 可解析 | 12s | 可用；仅内部检索 + 原帖溯源 |
| `linux-do` | `top.rss` / `latest.rss` | robots 门禁可判且允许请求；两个 feed 均遭 CF 403 | 10s | 显式 502；不绕过，改走人工摘录 |
| `manual-xhs` | 小红书人工复制粘贴 / 授权后的可见浏览器逐帖识图 | 后端不访问原站；浏览器仅低频人工审核公开页面 | N/A | 可用；不含自动采集器 |
| `manual-douyin` | 抖音人工复制粘贴 / 授权后的可见浏览器逐帖识图 | 后端不访问原站；用户登录后仅审核可见页面 | N/A | 可用；已完成 22 篇真实面经入库 |
| `manual-zhihu` | 知乎人工复制粘贴 / 授权后的可见浏览器阅读 | 后端不访问原站；用户自行登录后仅审核可见文章 | N/A | 可用；已完成 8 篇真实面经入库 |
| `manual-maimai` | 脉脉人工复制粘贴 | 不发任何网络请求 | N/A | 可用（首次导入时建 Source） |
| `manual-friend` | 朋友分享文本 | 不发任何网络请求 | N/A | 可用；广告样例被拒收 |

未接入知乎自动采集：对公开回答 URL 走 `PoliteClient` 实测，直接得到 `compliance_violation`，robots 禁止该路径。知乎搜索页未登录时只显示登录墙；用户自行完成登录后，才开始低频逐篇阅读可见文章。实现阶段没有编写或提交任何小红书/抖音/知乎自动采集代码；所有社交平台内容都经对应人工端点入库，不调用隐藏接口、不提取 Cookie、不做无人值守翻页。

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
| 小红书人工摘录 | 24 | 12/24（50.0%） | 407 | 1 | 两批共新增 23 篇；覆盖京东、字节、腾讯、百度、淘天、蔚来、追觅、去哪儿等，图文帖逐图识别 |
| 抖音人工摘录 | 22 | 14/22（63.6%） | 269 | 0 | 两批覆盖腾讯、字节、阿里、蚂蚁、美团、百度、快手、网易、小鹏、米哈游、联想、大疆、哔哩哔哩、美的及创业公司；逐帧读取滚动录屏与图文 |
| 知乎人工摘录 | 8 | 6/8（75.0%） | 162 | 0 | 覆盖字节多模态/豆包、腾讯混元、阿里夸克、通义实验室、淘天多模态和美团大模型；逐篇核验可见正文 |
| 朋友分享广告样例 | 0 | 0 | 0 | 0 | 明确资料领取/引流文本，`skipped_non_experience=1` |

总计 73 条面经、1092 个主问题、11 个追问链节点。CSDN 三篇都触及单帖 schema 的 30 题上限；浏览器辅助导入的面壁智能 9 图长帖同样触及上限（原帖 57 个提问点，人工转录其中 48 个技术相关提问，当前 schema 忠实保留前 30 个），新增淘天一面与知乎字节多模态三轮面经也达到 30 题上限。没有把同一场面试静默拆成多条记录。若后续要完整容纳超长帖或真正的“多家公司合一”长帖，应显式升级批量/分段模型并设计同场聚合语义。

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

浏览器实测 `/experiences`：显示来源 tab `牛客 16 / CSDN 3 / 小红书人工摘录 24 / 抖音人工摘录 22 / 知乎人工摘录 8`；点击“人工摘录”可见文本、五渠道、日期、URL 字段和“不访问原帖”说明；页面显示 `73/73 条面经`，新卡片均带来源和原帖链接。第二批抖音中的字节飞书、百度、快手、网易等，以及知乎中的字节、腾讯、美团、阿里等卡片均正常展示并可展开全部题目。

### 用户授权后的浏览器辅助人工批次

```text
京东 / 字节 / 腾讯 / 百度 / 面壁智能 / 淘天 / 小红书 / 地平线，共 8 篇
首次逐篇 POST /api/ingest/collect/manual：8 × inserted=1
同一批原样立即重跑：8 × duplicates=1, inserted=0
批次新增：8 条面经、150 个主问题
批次后总量：28 条；manual-xhs 9 条、153 个主问题、1 个追问
```

浏览器操作只覆盖可见搜索结果、帖子正文与图片轮播；跳过八股资料、引流和纯求职记录。没有读取浏览器 Cookie/本地存储，没有调用小红书隐藏接口，也没有把浏览器流程写成仓库内的自动化采集器。

### 第二批小红书扩充与抖音入口

```text
蔚来 / 字节 / 百度 / 淘宝闪购 / 淘天 / 追觅 / 腾讯 / 京东 / 去哪儿等，共 15 篇
首次逐篇 POST /api/ingest/collect/manual：15 × inserted=1
同一批原样立即重跑：15 × duplicates=1, inserted=0
批次新增：15 条面经、254 个主问题
批次后总量：43 条；manual-xhs 24 条、407 个主问题、1 个追问
```

第二批额外跳过了 JD 推演、题库引流、十家公司混帖、只有封面没有问题的帖子，以及一条把既有腾讯面经近乎逐句改成“字节”的搬运内容。抖音已新增独立 `manual-douyin` SourceSpec、接口别名和页面来源选项；浏览器直达抖音搜索后仍出现“登录后即可搜索更多精彩视频”，因此暂停站内内容读取，未尝试绕过登录、验证码或访问隐藏接口。

### 用户登录后的抖音人工批次

```text
腾讯 / 美团 / 字节 / 米哈游 / 联想 / 大疆 / 哔哩哔哩 / 美的 / 某小公司 Agent 岗，共 9 篇
首次逐篇 POST /api/ingest/collect/manual：9 × inserted=1
同一批原样立即重跑：9 × duplicates=1, inserted=0
批次新增：9 条面经、114 个主问题
批次后总量：52 条；manual-douyin 9 条、114 个主问题
```

抖音图文中既有静态截图，也有手机备忘录滚动录屏。采集仅对浏览器可见画面做低频逐帖、逐帧识别；保留 9 个规范化 `/note/{id}` 原帖 URL。筛掉了“高频模板”“高分答案”“模拟面试”等题库或营销内容，并优先保留发帖人明确表示亲历的记录。米哈游、联想、大疆、美的及匿名小公司不在现有公司词表，忠实保留为 unmatched，不临时扩表。

### 抖音第二个人工批次

```text
腾讯 / 字节飞书与海外直播 / 美团 / 蚂蚁 / 阿里 / 百度 / 快手 / 网易 / 小鹏 / FOSHO，共 13 篇
首次逐篇 POST /api/ingest/collect/manual：13 × inserted=1
同一批原样立即重跑：13 × duplicates=1, inserted=0
批次新增：13 条面经、155 个主问题
批次后总量：65 条；manual-douyin 22 条、269 个主问题
```

第二批扩展“大模型面经”“AI 应用开发面经”等关键词，覆盖 Agent/RAG、GraphRAG、Text2SQL、模型训练、多模态、Python 后端、数据库与系统设计。保留 13 个规范化 `/note/{id}` 原帖 URL；腾讯、字节、美团、蚂蚁、阿里、百度、快手、网易均命中现有公司词表，`FOSHO AI`、`阿里淘天`、`小鹏汽车`按精确匹配约束保留为 unmatched。页面实测 `65/65`、`抖音人工摘录 22`，字节飞书 17 题、百度 15 题、网易 12 题等均可完整展开。

### 用户登录后的知乎人工批次

```text
字节多模态 / 腾讯混元 / 阿里夸克 / 美团算法与日常实习 / 通义实验室 / 字节豆包 / 淘天多模态，共 8 篇
首次逐篇 POST /api/ingest/collect/manual：8 × inserted=1
同一批原样立即重跑：8 × duplicates=1, inserted=0
批次新增：8 条面经、162 个主问题
批次后总量：73 条；manual-zhihu 8 条、162 个主问题
```

知乎搜索页未登录时只显示登录墙，用户自行完成登录后才开始读取。逐篇打开规范化专栏原文，核对作者、部门/岗位、轮次、正文问题和发布日期；跳过顶部 AI 汇总、LeetCode 题库推广、一篇与已选字节文章问题高度重合的帖子，以及只有少量笼统问题的短帖。8 篇全部保留原帖 URL；`阿里夸克`、`阿里巴巴通义实验室`未精确命中公司词表，其余 6 篇正常匹配。页面实测 `73/73`、`知乎人工摘录 8`，腾讯混元 25 题、字节多模态 30 题、美团日常实习 22 题等均可完整展开。

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
pytest                                              16 passed
npx tsc --noEmit --incremental false                passed
npm run build                                       passed
```

Next production build 首次在受限沙箱的 TypeScript worker 处报 `spawn EPERM`；相同构建获准在沙箱外执行后完整通过（10/10 静态页），属于进程权限而非代码错误。

## 5. 踩坑与遗留

- 牛客 `page` 是无效 SSR 参数；若未来站点提供公开分页链接，必须重新抓包/实测并继续经过 PoliteClient，不能复用猜测接口。
- 牛客偶发 200 空壳；当前只允许一次同 URL、同 UA、同 8 秒门禁的重试，失败显式上抛。
- linux.do RSS 与 JSON 当前均受 CF；不要加入 cookie、登录态、浏览器指纹或挑战绕过。可用路径仍是人工摘录。
- 知乎 robots 当前禁止目标回答路径；规则变化前不接自动采集。可见浏览器未登录搜索页只显示登录墙；用户自行登录后已通过低频人工审核完成首批 8 篇入库。
- CSDN 的 `阿里淘天` 与牛客的 `虾皮` 未命中公司词表是预期行为；本次没有改公司表。
- 人工来源中的 URL 只存储作溯源，不会被后端访问；`manual://...` Source base URL 进一步避免误用。
- 图片型长帖可能超过 `ExperienceDraft.items` 的 30 题上限；本批面壁智能帖子已显式记录截断。后续若扩容，应先设计同场分段与重组，避免为了题量制造重复面经卡片。
- 抖音登录与首批采集已经完成；后续若会话失效，应再次由用户自行登录或处理验证码，不把登录墙当成可绕过的技术故障。
- 工作区原有 `apps/web/tsconfig.tsbuildinfo` 未提交改动始终未暂存、未覆盖。

## 6. Git 提交清单

```text
1077968 扩充牛客面经多话题采集
c4a6d39 接入CSDN公开面经采集
dfb2eec 扩展linux.do公开RSS采集
b8b4ceb 新增面经人工摘录闭环
702e0c0 新增抖音人工摘录并扩充小红书面经
250982b 完成抖音面经人工采集批次
```

文档续十八与本总结由后续文档提交承载。所有功能提交均在 `main`，提交者沿用仓库配置 `fjnuslw`。
