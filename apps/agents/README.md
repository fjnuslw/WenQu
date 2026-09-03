# get_offer agents — 面试/拷打 agent 运行时

基于 **pi 生态**（MIT）的面试 agent 服务，负责 mock / grill / answer 三类会话编排。

## 代码归属（复用 vs 自研）

| 部分 | 来源 |
|---|---|
| agent 循环 / 事件流 / LLM provider | `@earendil-works/pi-agent-core` + `@earendil-works/pi-ai` 0.84.3（钉版） |
| F3 决策协议、状态机、Policy、编排、Prompt、事件 | 自研（`src/interview/`），经 `index.ts` 向会话层暴露单一入口 |
| F4/answer legacy 状态与 Prompt | 自研（`state-machine.ts` / `prompts.ts`），提示阶梯思路改编自 The-Interview-Mentor（MIT） |
| SSE 桥接 | 自研 `queue.ts`（同步事件回调 → 异步迭代） |
| 会话日志 | JSONL append-only（pi/dsh 同款设计） |

pi 的 provider 创建收敛在 `src/pi.ts`；F3 的 pi 工具适配收敛在
`src/interview/control-tools.ts`，领域状态机和 Policy 不依赖 pi。

## 运行

```bash
cp .env.example .env      # 填 DEEPSEEK_API_KEY
npm install
npm run typecheck
npm run dev               # http://localhost:23481
# 或 npm run build && npm start（生产构建）
```

## API

- `POST /sessions` `{mode, persona:{role, company?, style?, jd?, resumeHighlights?}, maxQuestionsPerPhase, maxFollowUpDepth, questions}` → `{id}`（`mode=mock` 时 `questions` 必须非空）
- `POST /sessions/:id/turn` `{text}` → SSE：`text_delta` / `phase` / `followup` / `decision` / `final` / `error`
- `GET /sessions/:id` → 状态快照

F3 题单面试不再接收客户端判定字段。面试官模型每轮只通过 `probe_answer` / `advance_question`
请求控制动作，Harness 负责追问上限、题号、阶段和结束条件；协议异常保持当前题，不会缺省推进。

## 阶段契约

F3 题单面试从 `self_intro` 开始，随后严格按题单题型投影到
`project / knowledge / scenario`，题单耗尽进入 `closing`；当前 target、题号与追问深度
均由 `src/interview/state-machine.ts` 管理。F4/answer 的 legacy 阶段状态机仍独立保留。
Phase G1 的拷打模式（只读工具面 + repo 检索工具）在此服务上扩展，工具经
`API_BASE_URL` 指向 apps/api 的内部端点。
