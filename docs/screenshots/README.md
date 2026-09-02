# WenQu README 演示资产

根 README 只使用 `v2/` 中由当前生产构建重新操作得到的截图。2026-09-02 已移除全部历史界面图，不做裁剪翻新或混用。

## 当前截图与任务

| 文件 | 实际演示任务 |
|---|---|
| `01-dashboard.png` | 工作台统计、今日复习与五条学习路径总览 |
| `02-learning-paths.png` | 五条路径、109 个节点与资源核验状态 |
| `02-learning-task.png` | “调通第一个调用”节点的产出物、两条验收与资源锚点 |
| `03-question-bank-rag.png` | 用 RAG 标签筛出 2,521 道题并查看公司来源 |
| `03b-question-assistant.png` | 答题助手的口头版、原理、公式与追问 |
| `04-experiences-meituan.png` | 按美团筛选中文大模型 / Agent 面经问题树 |
| `05-interview-deep-dive-voice.png` | 合成经历的量化深挖、中文阶段状态与浏览器音色选择 |
| `06-grill-repo-evidence.png` | 真实代码问题与项目文件树并排核证 |
| `07-repository-intelligence-evidence.png` | 点击文件后查看源码内容与行号 |
| `08-resume-jd-synthetic.png` | 合成简历与合成 JD 的 88/100 匹配报告 |
| `09-review-sm2-synthetic.png` | 三张合成失分卡的 SM-2 队列 |
| `10-evidence-report-synthetic.png` | 合成面试的逐项证据评分与复习建议 |

## 可复现的安全演示

先启动 API，再运行：

```bat
apps\api\.venv\Scripts\python.exe apps\api\scripts\seed_readme_showcase.py
```

然后使用以下只读展示入口：

- `/resume?showcase=1`：只显示 `README_SHOWCASE_SYNTHETIC_RESUME.pdf`；
- `/review?showcase=1`：只显示 `README_SHOWCASE_SYNTHETIC_SESSION` 的失分卡。

脚本幂等更新合成记录，不读取真实简历，也不会调用外部模型。JD 匹配本身会调用已配置的 LLM，但输入仅包含仓库内合成简历和人工编写的合成 JD。

## 截图门禁

- 只使用合成候选人、合成简历和可公开仓库；禁止显示真实姓名、电话、邮箱、住址、真实文件名、API Key 或 token。
- 尺寸统一为 1440×900、暗色主题、桌面断点；先在生产构建验证，再保存 PNG。
- 每张图只讲一个具体任务；截图前检查地址、通知、路径、Git remote、日志、报错与右侧面板。
- 任何新截图替换后都要再次人工检查可见文本，并同步更新根 README 的任务说明。

品牌封面和三层能力图位于 `docs/assets/`；架构图的可编辑 HTML 源文件位于 `apps/web/public/readme-architecture.html`。
