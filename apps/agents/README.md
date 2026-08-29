# get_offer agents — 面试/拷打 agent 运行时

基于 **pi 生态**（MIT）的面试 agent 服务。spec：`docs/spec.md` §2/§5.2。

## 代码归属（复用 vs 自研）

| 部分 | 来源 |
|---|---|
| agent 循环 / 事件流 / LLM provider | `@earendil-works/pi-agent-core` + `@earendil-works/pi-ai` 0.84.3（钉版） |
| 阶段状态机、4 级提示阶梯、导演指令 | 自研（`state-machine.ts` / `prompts.ts`），阶梯思路改编自 The-Interview-Mentor（MIT） |
| SSE 桥接 | 自研 `queue.ts`（同步事件回调 → 异步迭代） |
| 会话日志 | JSONL append-only（pi/dsh 同款设计） |

pi 的 API 接触面收敛在 `src/pi.ts` 与 `session.ts#lastAssistantText` 两处——pi 升级只改这两处。

## 运行

```bash
cp .env.example .env      # 填 DEEPSEEK_API_KEY
npm install
npm run typecheck
npm run dev               # http://localhost:8787
```

## API

- `POST /sessions` `{mode, persona:{role, company?, style?, jd?, resumeHighlights?}, maxQuestionsPerPhase, maxFollowUpDepth}` → `{id}`
- `POST /sessions/:id/turn` `{text, vagueAnswer?}` → SSE：`text_delta` / `phase` / `followup` / `final` / `error`
- `GET /sessions/:id` → 状态快照

`vagueAnswer` 由 api 侧评审器（I1 里程碑）判定后传入；缺省按有效回答处理。

## 阶段契约（state-machine.ts）

opening → self_intro → project → knowledge → scenario → reverse → closing，
每阶段 `maxQuestionsPerPhase` 道题，追问链 `maxFollowUpDepth` 层打满记盲区换题。
Phase G1 的拷打模式（只读工具面 + repo 检索工具）在此服务上扩展，工具经
`API_BASE_URL` 调 apps/api 的内部端点（见 spec §5.1）。
