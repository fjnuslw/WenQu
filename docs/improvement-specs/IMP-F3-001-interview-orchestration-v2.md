# IMP-F3-001：模拟面试最小决策协议与 Harness 编排 v2

> 状态：**Verified**  
> 创建日期：2026-09-01  
> 父规范：[`docs/spec.md` F3](../spec.md#f3-ai-考官模拟面试)  
> 适用范围：`mode=mock` 的实时文字面试  
> 不改变：pi provider、组卷 API、评分报告数据结构、F4 项目拷打、语音方案

## 0. 决策摘要

F3 不迁移出 pi。问题位于交互编排层：当前系统在模型判断候选人回答之前，依赖一个实际上没有调用方提供的 `vagueAnswer` 字段推进题单，导致 Prompt 虽然要求追问，运行时却几乎总是直接换题。

v2 采用以下设计：

1. 删除客户端参与追问判断的 `vagueAnswer` 协议。
2. 给面试官模型只暴露两个稳定的控制工具：`probe_answer` 和 `advance_question`。
3. 模型只选择动作并自然表达问题；题号、阶段、追问深度、预算、结束条件和日志全部由 Harness 管理。
4. 实时对话不要求模型填写 `sufficiency / coveredPoints / missingPoints / followUpKind` 等大对象。
5. 详细评分和知识点抽取继续由面试结束后的 evaluator 完成，不反向控制实时状态机。
6. 任意协议错误都保持当前题，绝不再以“缺省有效回答”静默推进。

核心原则：**约束动作，不约束语言；复杂状态留在 Harness，不让模型填写状态表。**

## 1. 现状与根因

### 1.1 改造前已确认的执行链

下表是 2026-09-01 创建本 Spec 时的代码快照，用于保留根因证据；对应分支现已由 v2 替换。

| 环节 | 改造前行为 | 当时证据 |
|---|---|---|
| Web 提交 | 每轮只发送 `{ text }` | `apps/web/src/components/interview/chat-room.tsx:413-417` |
| Agents API | 接受可选 `vagueAnswer?: boolean` | `apps/agents/src/server.ts:83-86` |
| 会话推进 | 只有 `vagueAnswer === true` 才追问；缺省进入换题分支 | `apps/agents/src/session.ts:201-239` |
| 模型调用时序 | 状态机先决定追问/换题，再把候选人回答交给 pi | `apps/agents/src/session.ts:182-267` |
| Prompt | 声称模型会判断含糊并执行四级追问 | `apps/agents/src/prompts.ts:129-139` |

因此，改造前实现同时存在两个互相冲突的事实：Prompt 把判断责任交给模型，代码却要求外部调用方事先给出判断。Web 没有评审器，也没有发送该字段，最终形成稳定但错误的默认路径：**每轮回答都被视为充分，题目持续推进，`followUpDepth` 长期为 0。**

### 1.2 核心问题不是 pi 不适配

`apps/agents/src/pi.ts` 已经支持向 pi Agent 注册 `AgentTool[]`；F4 和答题模式也已经分别使用代码检索工具与联网工具。缺少的是 F3 自己的控制工具和工具执行后的确定性状态提交，而不是底层模型循环能力。

### 1.3 当前验收指标的不足

父 Spec 使用“30 分钟产生不少于 8 条追问链”验证 F3。该指标能发现完全不追问，但不能区分“有效深挖”和“为了凑数而追问”。v2 保留它作为覆盖度指标，同时增加决策准确率、误追问率、追问相关性和状态安全性指标。

## 2. 目标与非目标

### 2.1 目标

- 每个需要评估的候选人回答都产生一个可审计的控制动作。
- 完整回答进入下一题；含糊、局部正确、答非所问或证据不足时围绕当前回答追问。
- 追问不脱离候选人原话和当前题，不提前泄露参考答案。
- 状态转换 exactly-once；模型重复调用工具也不能重复推进。
- 模型可见协议保持小、稳定，便于更换模型和单独优化 Prompt。
- 决策、状态机、Prompt、题目选择、报告评价和 UI 可以分别测试与替换。
- 全链路可回放，能够解释“为什么这轮停留在原题或进入下一题”。

### 2.2 非目标

- 不在本 Spec 内更换 pi 或直接引入 DeepSeek Harness 运行时。
- 不把实时面试改成多 Agent 辩论或额外常驻评审 Agent。
- 不重做组卷、简历解析、评分报告和失分点回流。
- 不处理 F4 读码拷打的工具编排；F4 后续只复用这里沉淀的通用接口。
- 不把语音、情绪、语速或填充词分析纳入本轮。
- 不以暴露模型思维链作为可观测性方案。

## 3. 设计原则

### 3.1 单一决策所有者

“追问还是换题”只能由面试官模型请求、Harness 校验并提交。Web、API 和 Prompt 不得各自维护一套隐式判断。

### 3.2 模型界面最小化

DeepSeek Harness 的可借鉴点不是字段多，而是内部能力丰富、模型可见面很窄：每一步只组装当前 Agent 可见的 Prompt 和工具 schema，工具执行、policy、事件和持久状态留在 Harness 内部。参见 [`references/deepseek-harness/docs/architecture.zh.md`](../../references/deepseek-harness/docs/architecture.zh.md#轮次流程) 与 [`research/03-agent-harness与项目拷打技术.md`](../../research/03-agent-harness与项目拷打技术.md)。

F3 遵守同一原则：

| 信息 | 是否让模型输出 | 归属 |
|---|---:|---|
| 追问或换题 | 是 | 控制工具名 |
| 自然语言追问 | 是 | `probe_answer.question`（唯一自由文本字段） |
| 下一题/收尾措辞 | 否 | Harness 从题单确定性生成 |
| 当前题号、阶段、追问深度 | 否 | Runtime state |
| 最大深度、题目预算、强制换题 | 否 | Policy |
| covered/missing points、评分、盲区 | 否 | Post-session evaluator |
| 决策耗时、重试、工具异常 | 否 | Event log / metrics |

### 3.3 失败时保持现场

决策缺失、参数非法、模型超时或工具重复调用时，默认行为是保留当前题和当前深度。任何异常都不能被解释为 `advance`。

### 3.4 先提交动作，再展示语言

面试官给用户的本轮文字只有在控制动作成功提交后才能进入可见流，防止 UI 已经显示“继续追问”，状态却已经换到下一题。

### 3.5 稳定 schema，内部可扩展

整个 `mode=mock` 会话稳定暴露同一组两个工具，以保持 Prompt/工具前缀稳定。新的自适应策略优先增加内部 policy 或工具返回指令，不为每项能力增加模型必填字段。

## 4. 目标架构

```text
候选人回答 { text }
        │
        ▼
InterviewOrchestrator ──读取──► RuntimeState + 当前题 + 参考要点
        │
        ├─ 注入最小当前轮上下文
        ▼
pi Agent 单步：理解回答，只调用一个控制工具
        │
        ├─ probe_answer({ question })
        └─ advance_question({})
        │
        ▼
DecisionPolicy ──校验深度/阶段/题单边界──► 原子提交状态 + 追加事件
        │
        ▼
Harness：probe 发布 question；advance 准确发布下一题/收尾
        │
        ▼
SSE → Web；会话结束后 transcript → 独立 Evaluator → 报告/复习回流
```

这里仍遵循 DeepSeek Harness 的关键思想：模型只面对最小工具面，状态和副作用由运行时掌握。首版曾让工具结果触发第二个模型 step；同 fixture A/B 实测 p50 达旧路径 **2.82×**，超过 2.2× 预算，因此收敛成一个模型 step。`question` 只是可直接展示的自由语言，不是充分性、评分或状态字段；动作仍由工具名表达，也不解析自然语言控制标记。

## 5. 模型可见控制协议

### 5.1 `probe_answer`

用途：候选人回答仍值得围绕当前题继续深挖。

```ts
interface ProbeAnswerArgs {
  /** 候选人可见的单个自然追问；不是评分报告、分析表或思维链。 */
  question: string; // 1..240 chars
}
```

约束：

- `question` 是唯一字段，允许模型自由组织追问语言；不得再要求充分性、覆盖点或追问类型。
- 调用成功后当前题保持不变，`followUpDepth + 1`。
- Harness 只有在动作和事件成功提交后才把 `question` 发布给候选人。
- 提示层级在调用前由 Harness 注入，模型不需要回填枚举。

### 5.2 `advance_question`

用途：当前回答已经足够，或继续追问的收益低于进入下一题。

```ts
type AdvanceQuestionArgs = Record<string, never>;
```

约束：

- 无模型必填字段，动作由工具名表达。
- 调用成功后 Harness 决定下一题和阶段，并把真实题干返回给模型。
- 题单耗尽时 Harness 自动进入 `closing`；模型不拥有 `finish` 工具。

### 5.3 明确禁止的实时协议

以下大对象不得作为每轮实时必填输出：

```ts
// 禁止：字段彼此相关、迫使模型为了填表而拆解自然判断。
interface RejectedTurnAssessment {
  action: "probe" | "advance";
  sufficiency: number;
  coveredPoints: string[];
  missingPoints: string[];
  followUpKind: "detail" | "scenario" | "hint" | "challenge";
}
```

这些信息若对报告有价值，应从完整 transcript 离线提取，而不是耦合到实时状态推进。

## 6. Harness 内部状态与策略

模型不填写内部状态。建议的规范化状态为：

```ts
interface InterviewRuntimeState {
  status: "active" | "closing" | "finished";
  phase: Phase;
  currentTarget:
    | { kind: "self_intro" }
    | { kind: "plan_question"; index: number }
    | { kind: "reverse" }
    | null;
  questionsInPhase: number;
  followUpDepth: number;
  turnNo: number;
}
```

`currentTarget` 明确表示候选人正在回应什么：自我介绍、题单问题或反问环节。题单索引只在 `kind=plan_question` 时存在，不再让一个自增后的 `qIndex` 同时承担“当前题”和“下一题指针”两种语义。

### 6.1 状态转换表

| 前置状态 | 模型请求 | Policy 应用结果 | 状态变化 |
|---|---|---|---|
| `self_intro` | `probe_answer` | 深挖自我介绍中的项目/职责 | target 不变，深度 `+1` |
| `self_intro` | `advance_question` | 引入第一道题单题 | target 切到 `plan_question(0)` |
| 当前题存在，深度未达上限 | `probe_answer` | 接受追问 | 当前题不变，深度 `+1` |
| 当前题存在，深度已达上限 | `probe_answer` | 强制换题 | 记录 `followup_cap`，切下一题，深度归零 |
| 当前题存在 | `advance_question` | 接受换题 | 切下一题，深度归零 |
| 已是最后一题 | `advance_question` | 自动收尾 | `status=closing` |
| `closing/finished` | 任一控制工具 | 拒绝 | 状态不变 |
| 无控制工具 | 一次纠错重试 | 仍失败则安全兜底 | 状态不变 |
| 同轮第二次控制调用 | 拒绝重复提交 | 首次提交有效 | 不发生第二次转换 |

### 6.2 必须保持的不变量

1. 每个候选人回答最多提交一次状态转换。
2. `followUpDepth` 永不超过 `maxFollowUpDepth`。
3. `probe` 不改变当前题；`advance` 必须改变当前题或进入 closing。
4. 下一题题干只能由 Harness 从题单取得，模型不能改写成另一道题。
5. 状态提交前的 assistant 文本不发送到 Web。
6. 每次状态提交都有持久事件；每段模型可见上下文可由日志重建。

## 7. 单轮时序

### 7.1 自我介绍与首题引入

新建会话后，Harness 先把 `currentTarget` 设为 `self_intro`。当前 UI 要求候选人先用一句自我介绍开场，因此首个候选人消息是对该 target 的回答，也必须经过控制工具：内容值得深挖时 `probe_answer`，足够清楚时 `advance_question` 并引入题单第一题。这样既不把自我介绍误算成第一道技术题，也不会跳过父 Spec 要求的自我介绍追问。

如果以后改成面试官自动先开口，只需调整启动 transport；`self_intro` target 和后续决策协议不变。

### 7.2 正常回答轮

1. 接收并持久化候选人原话。
2. 读取当前题、参考要点、追问素材和内部深度。
3. 注入当前轮上下文，但不提前注入下一题。
4. 开启输出闸门：临时缓冲模型文本，不直接发送 SSE。
5. pi 必须调用 `probe_answer({question})` 或 `advance_question({})` 中的一个，工具外正文全部拦截。
6. 工具执行器校验并原子提交状态，写入 `interview_decision` 和 `state_transition`。
7. `probe` 发布已提交工具参数中的自由文本问题；`advance` 由 Harness 准确发布下一题或收尾。
8. 打开输出闸门，只发送第 7 步确定的 interviewer 文本；不再增加第二次模型往返。
9. 持久化 assistant 回复和最终状态，发送 `final`。

### 7.3 协议纠错

如果第一步直接输出文字而没有调用工具：

1. 丢弃尚未对用户可见的缓冲文字。
2. 注入一次简短纠错：“先调用且只调用一个控制工具，再生成面试官回复。”
3. 只允许一次自动重试。
4. 再次失败时返回固定的中性澄清语，保持当前题与深度，并记录 `protocol_error`；不得静默换题。

## 8. Prompt 与上下文规范

### 8.1 稳定 System Prompt

System Prompt 只包含角色、单题原则、工具选择规则、表达风格和安全边界。公司、简历、题单和实时深度继续通过会话上下文/每轮指令注入，避免破坏跨会话前缀缓存。

应加入的核心规则：

- 回答已经覆盖题目核心且能自洽：调用 `advance_question`。
- 回答含糊、只报术语、缺关键因果/指标、答非所问或仍可验证：调用 `probe_answer`。
- 先调用一个控制工具；工具成功后只输出一个清晰问题或收尾，不暴露工具和导演指令。
- 不得用固定长度、是否出现关键词等表面特征代替语义判断。

### 8.2 每轮上下文

模型可以看到但不需要回填：

- 当前题干与题型。
- 参考答案要点，仅用于判断和追问，禁止直接朗读。
- 当前追问素材和候选人原话。
- 当前提示层级/剩余追问预算的简短指令。

不得把整个 `SessionConfig`、完整 RuntimeState、内部指标或报告 schema 塞入每轮 Prompt。

### 8.3 追问质量

四级提示阶梯继续作为 Harness policy 的输出提示，而不是让模型选择枚举：

1. L1：直问候选人刚才回答中缺失的实现或因果细节。
2. L2：施加一个具体条件变化，检验方案边界。
3. L3：给方向性提示后降低难度重问。
4. L4：不再追问，由 Harness 记录盲区并推进。

## 9. 模块边界与建议目录

目标是让每块可以独立优化，而不是继续把状态推进、Prompt 拼装、pi 事件和日志混在 `session.ts`。

```text
apps/agents/src/interview/
  contracts.ts        # 控制动作、状态、领域事件；无 pi/Hono 依赖
  state-machine.ts    # 纯状态转换与不变量
  policy.ts           # 深度上限、强制推进、重试和结束策略
  control-tools.ts    # pi AgentTool 适配；只调用 policy/orchestrator
  orchestrator.ts     # 单轮生命周期、输出闸门、exactly-once
  prompts.ts          # mock 面试 Prompt 与每轮上下文
  events.ts           # append-only 领域事件与投影
  index.ts            # F3 对 session 层的唯一公开入口
```

| 模块 | 只负责 | 不负责 |
|---|---|---|
| `pi.ts` | provider/model/Agent 创建 | 面试状态与业务判断 |
| `interview/orchestrator.ts` | 轮次顺序、动作提交、输出闸门 | 组卷与报告评分 |
| `interview/state-machine.ts` | 纯转换 | Prompt、网络、文件 I/O |
| `interview/policy.ts` | 上限、兜底、推进规则 | 自然语言生成 |
| `interview/prompts.ts` | 模型行为和语言风格 | 修改状态 |
| `session.ts` | 会话生命周期和持久化接线 | 内联 F3 决策分支 |
| `server.ts` | HTTP/SSE 校验与传输 | 推断回答质量 |
| `apps/api` | 组卷、报告、复习回流 | 实时追问开关 |
| Web | 输入和事件呈现 | 生成或补充决策字段 |

F4 将来可以复用 `orchestrator/policy/events` 接口，但使用自己的工具集合和 Prompt；本 Spec 不强制同步迁移 F4。

## 10. 外部接口与事件

### 10.1 HTTP

保持现有 URL，收窄请求体：

```http
POST /sessions/:id/turn
Content-Type: application/json

{ "text": "候选人的回答" }
```

- 从公开契约和 README 删除 `vagueAnswer`。
- Web 无需增加字段，因其当前已经只发送 `{ text }`。
- 服务端 schema 应拒绝或显式报告未知控制字段，不能再次静默解释默认值。

### 10.2 SSE

保留现有 `phase / followup / question / text_delta / final / error`，新增可审计但不暴露内部推理的事件：

```ts
type InterviewDecisionEvent = {
  type: "decision";
  action: "probe" | "advance";
  followUpDepth: number;
  forced: boolean;
};
```

Web 可用该事件更新追问徽标；旧 `followup` 在一个兼容周期内保留，随后由统一状态事件替代。

### 10.3 持久事件

建议至少追加：

```ts
interface InterviewDecisionRecord {
  type: "interview_decision";
  turnNo: number;
  requestedAction: "probe" | "advance";
  appliedAction: "probe" | "advance";
  followUpQuestion?: string;
  questionId: number | null;
  depthBefore: number;
  depthAfter: number;
  forcedByPolicy: boolean;
  reasonCode?: "followup_cap" | "protocol_fallback";
}
```

除工具名表达的 `requestedAction` 和 `probe` 的自由文本 `followUpQuestion` 外，其余字段都由运行时派生。丰富的内部事件不会扩大模型 schema。

## 11. 失败与恢复策略

| 故障 | 行为 | 状态 |
|---|---|---|
| 模型未调用控制工具 | 一次纠错重试；再失败返回中性澄清 | 不变 |
| 工具参数非法 | 返回工具错误并允许本轮纠正 | 不变 |
| 同轮重复调用 | 拒绝第二次，记录协议异常 | 保留首次提交结果 |
| 模型/API 超时 | SSE 返回可重试错误 | 不变 |
| `probe` 超过上限 | Policy 强制 `advance` 并记录原因 | 确定性推进 |
| 题单耗尽 | 自动 closing | 不访问越界题目 |
| 输出发生在动作之前 | 缓冲并丢弃该段，触发纠错 | 不变 |
| 日志写入失败 | 本轮不提交对外成功结果 | 保持可恢复边界 |

最后一条要求状态提交与日志追加具有明确的一致性顺序。MVP 可以使用单进程锁和“先写 decision event、再发布 SSE”；后续持久化升级不得改变领域协议。

## 12. 可观测性

必须记录而不要求模型填写：

- `decision_first_pass_rate`
- `decision_retry_rate`
- `protocol_error_count`
- `probe / advance / forced_advance` 数量
- 每题追问深度分布与触顶率
- `decision_latency_ms / total_turn_latency_ms`
- 下一题覆盖率、重复题率
- Prompt token、tool schema token、cache hit

不得把隐藏思维链作为验收证据。质量复盘使用候选人原话、控制动作、`followUpQuestion` 和状态转换。

## 13. 验收方案

### 13.1 纯逻辑测试（必须 100%）

- `probe` 保持当前题并增加深度。
- `advance` 切换到准确的下一题并归零深度。
- 触顶强制推进且只推进一次。
- 队列末尾稳定进入 closing，不越界、不重复结算。
- 缺失/非法/重复动作不会产生额外状态转换。
- 任意事件重放能得到相同 RuntimeState。

### 13.2 协议集成测试（Fake Agent）

- 请求体只有 `{ text }` 时可完成完整追问和换题链。
- 单个模型 step 调工具；动作提交后，只有 `probe.question` 或 Harness 下一题进入 SSE。
- `probe_answer` 与 `advance_question` 每轮至多一个成功。
- 模型直接说话时触发一次纠错；失败后不推进。
- 进程重试或客户端断连不造成重复换题。

### 13.3 模型质量评测

建立不少于 50 条人工标注 fixture，至少覆盖：完整回答、部分正确、术语堆砌、错误回答、答非所问、主动承认不会、被提示后改进、Prompt injection。

硬门槛：

- `probe / advance` 对人工金标准的一致率 ≥ 85%。
- 对完整回答的误追问率 ≤ 15%。
- 对含糊/局部回答的有效追问召回率 ≥ 85%。
- 追问与候选人原话/当前题相关率 ≥ 80%。
- 状态越界、无决策推进、同轮重复推进均为 0。
- 最大追问深度遵守率 100%。

### 13.4 长面验收

继续运行父 Spec 的 30 分钟文字面试，并保留“≥8 条追问链”作为覆盖检查；同时必须满足：

- 每个已回答题目都有一条 `interview_decision`。
- 抽样追问相关性和决策准确率达到上节门槛。
- 不因凑追问数量对完整回答反复纠缠。
- 报告引用的失分点能够回溯到真实回答和追问链。

链条数量不再能够单独判定 F3 已完成。

### 13.5 性能预算

- 正常轮次只允许一个模型 step，不引入工具后的第二次生成或独立常驻评审 Agent。
- 在相同模型、相同网络和同一 fixture 集上记录 v1/v2 的 p50、p95；v2 p50 不得超过 v1 的 2.2 倍。
- 工具 schema 在整个 mock 会话保持稳定，单个 `question` 最长 240 字符。
- 若性能未达标，优先优化 Prompt、缓存和 step 内容，不回退到解析自然语言控制标记。

## 14. 实施顺序

### 14.0 推进计划表

> 最近更新：2026-09-01  
> 更新规则：每个里程碑开始、完成或发生设计偏差时立即回写；`Verified` 必须附实际命令或验收证据。

| 里程碑 | 状态 | 计划产物 | 完成判据 | 实际结果 / 调整 |
|---|---|---|---|---|
| M0 Spec 基线 | ✅ Verified | 改进 Spec、职责边界、最小协议、计划表 | 文档可独立指导实现 | 本文已建立并随每次偏差回写；保留 pi，确定双工具一步协议 |
| M1 领域内核 | ✅ Verified | `interview/` contracts、纯状态机、policy、领域事件、单元测试 | 转换/上限/exactly-once/重放测试通过 | 最终 F3 测试套件 22/22；同步 claim、重复/并发保护、错误回滚、重放与跨题型计数均覆盖 |
| M2 最小工具协议 | ✅ Verified | 两个 AgentTool、turn orchestrator、输出闸门、协议重试；移除 `vagueAnswer` | `{text}` 可完成 probe/advance；异常不推进 | Fake Agent 与实模均为一步控制动作；协议外正文拦截，mock 无题单/未知字段显式 422，closing 后输入拒绝 |
| M3 事件与 UI | ✅ Verified | decision 持久事件、SSE 事件、Web 展示与旧事件兼容 | UI 状态完全由服务端事件驱动 | JSONL decision/transition + SSE decision + Web 实时/历史恢复接通；最终历史恢复为 closing、题卡为空、36 条消息、无 mock thinking 暴露 |
| M4 自动化验收 | ✅ Verified | Fake Agent 集成测试、质量 fixture、长面脚本适配、回归 | §13 自动化门槛通过；实模门槛有可复跑结果 | 实模 50/50、probe recall 100%、false probe 0%、重试 0；v2 p50 为旧路径 0.81×；严格长测 30.3 分钟、9 链、18/18 决策、0 错误、closing；追问相关 9/9 |
| M5 独立优化插槽 | ✅ Verified | Prompt/Policy/Selector/Evaluator 扩展边界复核 | 后续优化不改双工具公共协议 | F3 稳定 Prompt/上下文/逐轮指令全部归属 `interview/`；模块经 `index.ts` 暴露；`session.ts` 只保留生命周期/I/O 接线；F4/answer 独立；基线绑定实现签名 |

状态含义：`⏳ Pending` 未开始；`🔄 In progress` 正在实施；`✅ Completed` 代码与静态测试完成；`✅ Verified` 已通过该里程碑全部运行态验收；`⛔ Blocked` 已记录外部阻塞和复现方式。

### 14.1 实施调整记录

| 日期 | 发现 | 调整 | 影响 |
|---|---|---|---|
| 2026-09-01 | `vagueAnswer` 没有真实决策来源 | 删除该字段和对应分支，所有 mock 回答统一进入双工具协议 | 修复“缺省即推进”的根因 |
| 2026-09-01 | 无题单 mock 会绕回旧自动推进路径 | Web 强制组卷，HTTP 与领域入口共同拒绝空题单 | F3 只有一个生产编排，不保留双轨行为 |
| 2026-09-01 | 单轮 latch 的首次实现会在异步日志前留下并发窗口 | 增加同步 claim，并对整场会话增加 single-flight turn guard | 同轮重复工具与并发请求都不能重复换题 |
| 2026-09-01 | 新增领域事件会挤占评分器的 80 条日志窗口 | 评分器先筛 `user/assistant` 再截断 | 长面前几轮不会因 decision/transition 增多而丢失 |
| 2026-09-01 | 直接用本地题库做外部实模 soak 会产生未授权数据外发 | 验收驱动新增 `--synthetic`，只使用仓库内人工 fixture | 运行态验证不读取、不外发本地题库内容 |
| 2026-09-01 | 双 step 方案同 fixture p50 为旧单步路径 2.82×，超过 2.2× 预算；low 思考档 10/10 但延迟无实质改善 | `probe_answer` 改为只携带一个自由文本 `question`，工具成功即终止模型 loop；advance 由 Harness 发布下一题 | 最终一步协议 A/B p50 0.81×，当前实现签名下 50 条质量集 100% 准确率 |
| 2026-09-01 | `.env.example` 的 `../data/sessions` 与 API 的根目录 `data/sessions` 不同源 | 修正为 `../../data/sessions`，并在 session_start 记录模型/思考档/协议版本 | 手工 dev 与项目启动脚本共用日志目录，报告可找到面试记录 |
| 2026-09-01 | F3 Prompt 仍从通用 Prompt 文件借用提示阶梯和首轮上下文，无法真正独立优化 | 将稳定 System Prompt、会话上下文和追问策略全部收口到 `interview/prompts.ts`；新增稳定前缀测试 | F3 Prompt 可单独迭代，F4/answer 不受影响；当前实模基线提升至 50/50 |
| 2026-09-01 | 质量/性能基线只绑定 fixture，关键实现变化后陈旧基线仍可能显示通过 | 为 F3 Prompt、工具、Policy、状态机、编排及接入层生成 `implementationSha256`，自动测试校验签名 | 任一关键实现变化都会强制重跑基线 |
| 2026-09-01 | `npm start` 指向不存在的 `dist/server.ts` | 修正生产入口为 `dist/server.js`，并以构建产物启动最终验收服务 | 消除“构建成功但无法生产启动”的交付缺口 |
| 2026-09-01 | 长面脚本把父 Spec 的“30 分钟”放宽成“接近 30 分钟（≥25）” | 将 `MIN_MINUTES` 改为 30，并把 26.4 分钟成功运行降级为中间证据，按 105 秒间隔严格重跑 | 避免用脚本自降门槛制造假验收 |

### M1：领域内核

- 建立 `interview/` 目录、contracts、纯状态机、policy 和事件类型。
- 用 Fake Agent 完成状态/协议测试。
- 不改变线上行为。

### M2：最小工具协议

- 实现两个控制工具和 per-turn exactly-once latch。
- 调整调用时序：先让模型看回答，再由工具提交动作。
- 加入输出闸门和一次纠错重试。
- 请求体收敛到 `{ text }`，删除 `vagueAnswer` 的服务端分支与公开文档。

### M3：事件与 UI

- JSONL 增加 decision/transition/protocol_error 事件。
- SSE 增加 `decision`，Web 用真实事件展示追问深度。
- 验收脚本从 decision 事件统计，不再只推断 `followUpDepth` 序列。

### M4：质量评测与灰度

- 建立 50+ 人工 fixture 和长面回放集。
- 同一题单 A/B 对比 v1 与 v2。
- 通过硬门槛后将本文状态改为 `Verified`，删除 v1 编排开关、兼容测试和陈旧说明。

### M5：独立优化插槽

在不改变两工具协议的前提下，后续可以单独迭代：

- `Prompt/Persona`：公司风格和问题措辞。
- `DecisionPolicy`：不同题型的深度预算、自适应难度。
- `QuestionSelector`：题单重排、覆盖与去重。
- `ProbeStrategy`：提示阶梯和追问类型生成。
- `Evaluator`：评分维度、证据抽取和复习回流。
- `Transport`：文字、语音或实时流。

### 14.2 最终验证证据

所有实模运行只使用 `apps/agents/evals/f3-decision-fixtures.json` 中的仓库自建合成数据；未读取或外发本地题库、用户简历和既有用户会话。

| 验证面 | 最终结果 | 证据 |
|---|---:|---|
| 领域/协议/Fake Agent/基线测试 | 22/22 | `npm test` |
| Agents 类型与生产构建 | 通过 | `npm run typecheck`；`npm run build`；`npm start` 构建产物烟测 |
| API 全量回归 | 58/58 | `python -m pytest -q` |
| API F3 静态检查 | 通过 | `ruff check ... --ignore E501,B008`（忽略项是该 legacy router 的既有规则） |
| Web 类型与生产构建 | 通过 | `npm run typecheck`；`npm run build` |
| HTTP 契约 | 通过 | 空 mock 题单 422；旧 `vagueAnswer` 字段 422 |
| 实模决策质量 | 50/50；覆盖 100%；probe recall 100%；false probe 0%；重试 0 | `evals/f3-decision-baseline.json` |
| 同 fixture 性能 A/B | v1 p50 3352ms；v2 p50 2723ms；比值 0.812 | `evals/f3-performance-baseline.json` |
| 严格长面 | 30.3min；9 链；18/18 决策；0 错误；p50/p95 1693/3465ms；closing | `evals/f3-long-interview-baseline.json` |
| 追问相关性 | 9/9（100%） | `evals/f3-followup-relevance-audit.json` |
| 历史与结束边界 | 36 条对话恢复；closing；题卡清空；mock thinking 0；结束后输入拒绝 | 最终会话 `ca9ea8d9-de85-4e9d-9c32-21e1a561749c` |
| 报告兼容 | 控制事件不进入 transcript，超过 80 条控制事件也不挤掉真实对话 | `apps/api/tests/test_verify_f3_interview.py` |

质量/性能/长面三类基线均绑定当前关键实现的 `implementationSha256`。Prompt、工具、Policy、状态机、编排器或接入层变化后，测试会要求重新评测，不能沿用陈旧 PASS。

## 15. 完成定义

只有同时满足以下条件，才可声称本次面试交互优化完成：

1. Web/API 不再提供或依赖 `vagueAnswer`。
2. 每个回答由模型通过最小工具协议请求动作，Harness 原子提交。
3. 所有失败路径均 fail-safe，不存在“缺省推进”。
4. 状态机、工具协议和日志重放有自动化测试。
5. 人工 fixture、长面试与性能预算全部达标。
6. 评分报告仍可读取新日志并完成失分点回流。
7. F4/answer 模式回归通过，没有被 F3 重构耦合。

## 16. 已定事项

- **继续使用 pi**：其 AgentTool 与多 step loop 足以支撑该方案。
- **不引入实时独立评审 Agent**：避免双控制源、额外延迟和评价/表达不一致。
- **使用两个动作工具，不使用五字段 TurnAssessment**。
- **结束条件归 Harness**：不向模型提供 `finish`。
- **报告字段留在离线 evaluator**：实时协议只承担交互决策。
- **题单驱动是 `mode=mock` 的唯一生产路径**：无题单 legacy 分支已删除，避免双轨行为再次漂移。
