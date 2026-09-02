# IMP-F3-002：中文面试、简历证据化深挖与可替换语音输出

> 状态：**Implementing（M1–M4 代码已完成；真实神经音色试听待外部 Provider）**  
> 创建日期：2026-09-01  
> 父规范：[`docs/spec.md` F3](../spec.md#f3-ai-考官模拟面试)  
> 前置规范：[`IMP-F3-001`](./IMP-F3-001-interview-orchestration-v2.md)  
> 适用范围：`mode=mock` 的题单、实时问答展示和 TTS 输出  
> 不改变：F3 的 `probe_answer / advance_question` 双工具协议、pi provider、评分报告结构、F4 项目拷打

## 0. 决策摘要

当前“人机感强”不是一个 Prompt 句子能解决的问题，而是三个边界缺失：

1. **题目事实与候选人展示语言没有分层。** Harness 原样展示题库 `stem`，因此英文题干和书面化长题会直接进入中文面试。
2. **简历只参与标签召回，不是一等题源。** 组卷器用 `exam_tags` 召回通用题，再把 `highlights` 放进首轮上下文；题单本身没有“实习/项目声明题”，详细自我介绍一旦判定充分，就会直接跳到通用技术题。
3. **浏览器 TTS 被误当成稳定语音 Provider。** 当前代码拿 `speechSynthesis.getVoices()` 返回的第一个中文音色；音色取决于设备，且没有等待 `voiceschanged`、质量排序、服务端神经语音或失败可见性。

本 Spec 采用三层增量设计：

- `QuestionSource` 保存题目事实和证据；`QuestionPresentation` 负责指定面试语言下的候选人可见表达。
- 简历中的实习、项目和亮点先抽成 `ResumeAnchor`，再组成位于通用题之前的证据化题目；所有简历追问都能回指原始声明。
- Web 只依赖统一 `SpeechOutput` 接口；优先使用已配置的服务端神经 TTS，未配置时使用经过质量排序的浏览器中文音色。

核心原则：**事实不翻译丢失，展示不照抄题库；简历题必须有证据锚点；语音 Provider 可换，面试状态机不感知音频实现。**

## 1. 现状证据与根因

### 1.1 英文/中英混排不会自动切换

| 环节 | 当前行为 | 证据 |
|---|---|---|
| API 组卷 | 返回数据库原始 `Question.stem` | `apps/api/src/getoffer/api/routers/interview.py` |
| Agents 下一题 | `deterministicReply` 直接拼接 `questions[index].stem` | `apps/agents/src/interview/prompts.ts` |
| SSE / 历史恢复 | `question.stem` 原样发送和恢复 | `apps/agents/src/interview/orchestrator.ts`、`apps/agents/src/server.ts` |

这是 IMP-F3-001 “下一题不得被实时模型任意改写”的正确约束产生的副作用：确定性题单有了，但没有独立展示字段。修复方式不是让实时模型临场翻译，而是在组卷阶段一次性产出并校验 `display_stem`。

中文面试的语言规则：

- 提问句法和解释必须是自然中文。
- `RAG`、`Embedding`、`Reranker`、`ACL`、类名、函数名等有辨识价值的技术词保留原文。
- 不把一道题扩写成术语清单；候选人一次只接收一个主要问题。
- 原始 `stem` 继续用于溯源、检索和答案关联，不能被覆盖。

### 1.2 简历参与了召回，却没有进入真实面试流程

当前 API 会用 `exam_tags` 扩充候选题池，并让 LLM 选一半左右的“押题”；这仍然只是“与简历技术栈相似的通用题”。此外：

- `ResumeProfile` 只结构化 `projects`，没有一等 `experiences/internships`。
- `PlanQuestion` 没有 `source` 或 `grounding`，无法证明某题为何对该候选人提问。
- `self_intro` 的校准策略会对信息完整的自我介绍直接 `advance`；第一题若是通用 RAG 题，项目/实习自然被跳过。

因此截图中的行为不是模型“没看到”简历，而是运行时没有保证下一题来自简历。

### 1.3 声音难听是浏览器系统音色的确定性风险

当前 `useSpeechSynthesis`：

- 只调用一次 `getVoices().find(lang startsWith zh)`，未等待异步音色列表更新；
- 不区分 Natural/Neural、Online、普通系统音色或 eSpeak；
- 音色完全随操作系统和浏览器变化；
- 没有服务端 TTS、音频取消、错误状态或 Provider 信息。

MDN 明确说明 `getVoices()` 返回的是**当前设备可用**的音色列表，而不是产品可控制的统一音色。因此浏览器 TTS 只能作为本地回退，不能作为“真实语音”的质量承诺。

## 2. 开源调研与可借鉴结论

调研日期为 2026-09-01；stars 是调研时快照，只用于过滤社区成熟度，不作为质量指标。

### 2.1 专用模拟面试项目

按“开源、模拟面试、简历个性化、Agent/语音”检索后，没有找到达到 1k stars 且实现足够完整的专用项目。可见样本如 `IliaLarchenko/Interviewer`（约 119 stars）、`DeepInterview`（约 18 stars）以及若干个位数 stars 项目，能证明行业常见流程是“简历/JD → 题单 → 多轮追问 → 报告”，但不足以作为高成熟度实现依据。

结论：不伪造“高 Star 面试项目”背书；从高 Star 通用语音/Agent 框架借鉴模块边界，再用本项目的题库、简历证据和 F3 状态机实现领域流程。

### 2.2 高 Star 语音 Agent 框架

| 项目 | 调研时 stars | 值得借鉴 | 不直接迁移的原因 |
|---|---:|---|---|
| [Pipecat](https://github.com/pipecat-ai/pipecat) | 15.1k | STT/TTS/transport 可插拔管线、结构化 conversation flow | 当前产品仍是按键提交式文字主流程，全量引入会扩大部署与状态复杂度 |
| [LiveKit Agents](https://github.com/livekit/agents) | 13.9k | 将 VAD、STT、LLM、TTS、turn detection、interruptions 分层；原生测试/判定器 | WebRTC/VAD 属于后续全双工阶段，不能替代现有确定性 F3 Harness |
| [TEN Framework](https://github.com/TEN-framework/ten-framework) | 11.1k | VAD、turn detection 和 Provider extension 独立，支持 RTC/WebSocket | 本轮只需 TTS 输出适配层，不需要迁移整个实时媒体运行时 |

共同思路是：**对话领域状态与媒体管线分离；Provider 可换；打断、取消和错误是显式状态。**

### 2.3 高 Star 中文 TTS

| 项目 | 调研时 stars | 能力与约束 | 本项目决策 |
|---|---:|---|---|
| [CosyVoice](https://github.com/QwenAudio/CosyVoice) | 23.4k | Apache-2.0；中文/多语种、文本规范化、指令控制、双向流式，官方称首包可低至约 150ms；提供 FastAPI 部署 | **首选自托管适配目标**；先接 SFT HTTP 输出，后续再做真正 chunk streaming |
| [Fish Speech](https://github.com/fishaudio/fish-speech) | 29.8k | 多语言、克隆和低延迟能力强 | 代码/权重为 Fish Audio Research License，且高性能数据来自 H200；不作为默认商用基线 |
| [IndexTTS](https://github.com/index-tts/index-tts) | 22.7k | 中文表现、情感/时长/发音控制和零样本克隆突出 | 使用 bilibili Model Use License；作为可选评测候选，不直接绑定产品默认实现 |

语音首版使用 Provider 协议同时支持：

1. `cosyvoice`：对接官方 `/inference_sft`，服务端把 raw PCM 包装成 WAV。
2. `openai_compatible`：对接支持 `/audio/speech` 的托管或自建服务，密钥只在 API 侧。
3. `browser`：无服务配置时的本地回退，优先 Natural/Neural 中文音色并显式展示当前来源。

不使用非官方 `edge-tts` 作为生产默认项，避免依赖未承诺的第三方接口。

## 3. 目标与非目标

### 3.1 目标

- 中文场景 100% 使用自然中文提问句法，保留必要技术术语；英文场景必须由用户显式选择。
- 题目原始事实与展示文案分别存储、分别验收。
- 使用简历时，题单前部至少覆盖一个实习/经历锚点和一个项目锚点（材料存在时）。
- 每个简历题都有 `grounding.kind / label / evidence`，不可凭空构造候选人经历。
- 详细自我介绍后进入首个简历深挖题，而不是随机通用题。
- TTS Provider 可独立替换；高质量 Provider 失败时显式报错，不悄悄换成另一种声音。
- 当前 F3 实时模型协议仍只有两个动作工具；新增字段由 Planner/Harness 管理。

### 3.2 非目标

- 本轮不把按键提交式面试改造成全双工 WebRTC。
- 不在主仓库下载数 GB 模型权重或自动启动 GPU 容器。
- 不做未经授权的真人声音克隆；若未来支持，必须增加声音授权和删除机制。
- 不把简历全文反复塞进每轮 Prompt；只注入当前题对应的最小证据。
- 不用翻译覆盖数据库原始题干。

## 4. 目标架构

```text
ResumeProfile ──抽取──► ResumeAnchor[] ──确定性配额/排序──┐
                                                         ├─► InterviewPlan[]
Question DB ──召回/选题──► CanonicalQuestion ──本地化───┘
                                                         │
                              stem (事实/检索)            │ display_stem (候选人可见)
                                                         ▼
                F3 Harness: probe / advance + grounding 校验
                                                         │
                              text_delta / question event │
                                                         ▼
                       SpeechOutput
                 ┌───────────┴───────────┐
          Server Neural TTS         Browser TTS fallback
       CosyVoice / compatible      ranked zh-CN voices
```

模块职责：

| 模块 | 负责 | 不负责 |
|---|---|---|
| API `interview/planning.py` | 简历锚点、配额、题源顺序、展示语言校验 | 实时追问决策 |
| API `interview` router | 数据检索、调用组卷 LLM、拼装响应 | 修改 F3 状态 |
| Agents `question-plan.ts` | 选择候选人可见题干、最小 grounding 指令 | 翻译、简历解析 |
| F3 `orchestrator/policy` | probe/advance、深度、结束边界 | TTS 和音色 |
| API `voice/gateway.py` | Provider 配置、上游请求、音频格式 | 面试文本生成 |
| Web `useSpeechSynthesis` | Provider 选择、播放/取消、错误展示 | 隐式切换 Provider |

## 5. 数据与接口

### 5.1 面试语言

```ts
type InterviewLanguage = "zh-CN" | "en-US";
```

- 开始页默认 `zh-CN`；只有用户显式选择才进入 `en-US`。
- `POST /api/interview/plan` 接收 `language`。
- `PersonaConfig.interviewLanguage` 告诉实时模型追问用什么语言，但下一题仍由 Harness 使用 `displayStem` 确定性发布。

### 5.2 题单项

```ts
interface PlanQuestion {
  id: number;
  stem: string;          // canonical，不覆盖
  displayStem: string;   // candidate-facing
  kind: string;
  answer: string | null;
  source: "bank" | "resume";
  grounding?: {
    kind: "experience" | "project" | "highlight";
    label: string;
    evidence: string;    // 简历原声明；只供判断/追问，不念成答案
  };
  probes?: string[];
}
```

这些字段属于题单和 Harness，不是实时模型每轮要填写的 JSON。实时模型可见控制 schema 不增加字段，避免“为了填表限制模型能力”。

### 5.3 题单配额

- 总题数含简历题和题库题。
- 8 题默认 3 道简历题、5 道题库题；4–5 题为 2 道简历题；3 题为 1 道简历题。
- 材料同时含经历与项目时，前两道分别覆盖两类；其余按原材料顺序补齐。
- 简历题永远排在题库题之前，使详细自我介绍后的第一次 `advance` 必然进入证据化深挖。
- 没有选择简历时，全部使用题库题，不伪造简历题。

### 5.4 语音接口

```http
GET  /api/voice/capabilities
POST /api/voice/tts   { "text": "..." }
```

- `capabilities` 只公开 Provider 名、音色名和是否可用，不公开密钥或内部地址。
- `tts` 文本长度受限；音色由部署配置决定，客户端不能指定任意上游参数。
- `openai_compatible` 返回上游音频；`cosyvoice` 把官方 raw PCM 包装为标准 WAV。
- 已配置神经 TTS 时失败必须显示错误；只有“未配置”时才使用浏览器回退。

## 6. Prompt 与交互规则

### 6.1 Planner

- 对每道题库题产出一个 `display_stem`，保持考察意图，不添加答案或新事实。
- 中文输出以中文组织句法；只保留有意义的英文术语和代码标识。
- 把过长书面题收敛成一个主要问题，其余细节交给 F3 追问。

### 6.2 实时面试官

- `probe_answer.question` 必须遵守本场语言。
- 简历/自述追问只能引用 `grounding.evidence` 或候选人刚刚说过的内容。
- 当前是简历题时，优先核实个人职责、真实实现、技术取舍、指标或复盘中的一个缺口；一次只问一个核心点。
- 当前是题库题时，不因首轮上下文里存在简历亮点而硬拉回无关项目。

### 6.3 UI

- 当前题卡显示“简历深挖 / 题库”来源，便于用户判断个性化是否真实生效。
- TTS 按钮 title 显示“神经语音 · Provider/音色”或“系统语音 · 音色”。
- TTS 请求/播放可被下一轮打断；错误单独展示，不污染面试错误状态。

## 7. 失败策略

| 故障 | 行为 |
|---|---|
| `zh-CN` 的 `display_stem` 不含足够中文句法 | 组卷失败并报告本地化错误，不把英文原题泄漏到会话 |
| Planner 漏掉本来已经是中文的展示项 | 可使用 canonical stem，但仍受长度/语言校验 |
| 简历锚点不足 | 按真实数量降低简历题配额，用题库题补齐；不复制、不编造 |
| grounding id 越界/重复 | 丢弃非法项并用确定性锚点模板补齐 |
| 神经 TTS 未配置 | 明确使用浏览器回退 |
| 神经 TTS 已配置但调用失败 | UI 显示失败，不静默换音色/Provider |
| 浏览器音色列表尚未加载 | 等待 `voiceschanged`；仍为空时使用浏览器默认并标注 |
| 新一轮回复到达 | abort 上游请求、暂停旧音频、撤销对象 URL，再播放新回复 |

## 8. 验收标准

### 8.1 题目语言

- 20 条包含纯英文、中文、混合技术词的 fixture：`zh-CN` 展示语言通过率 100%。
- 原始 `stem` 与题库记录一致，`display_stem` 不覆盖 canonical。
- `RAG/ACL/API/Embedding` 等技术词不会被错误意译；代码标识保持原样。
- 候选人可见题干长度 ≤ 240 字符，且只有一个主要问题。

### 8.2 简历证据

- 新上传简历能分别结构化 `experiences` 和 `projects`。
- 同时有经历和项目的 8 题计划：简历题 3 道，前两题覆盖两类，剩余 5 道为题库题。
- 每道 `source=resume` 的题都含合法 `grounding`，题干能回指 `evidence`。
- 无简历计划的 `source=resume` 数量严格为 0。
- 详细自我介绍后第一次 `advance` 发布第一道简历题。

### 8.3 语音

- Provider 配置和 API key 不进入浏览器响应或日志。
- OpenAI-compatible 与 CosyVoice adapter 均有 mock 上游测试；CosyVoice 输出是浏览器可播放的 WAV。
- 浏览器音色排序测试/静态规则优先 Natural/Neural `zh-CN`，拒绝选择明显低质的 eSpeak（存在更优选项时）。
- 新回复能取消旧请求/旧音频；已配置 Provider 失败可见且不静默回退。
- 真机人工试听至少比较 3 个中文问题，记录首音频延迟和 1–5 分自然度；未试听不得将语音里程碑标记为 Verified。

### 8.4 回归

- Agents 单测、typecheck、build 全通过。
- API 全量 pytest、ruff 通过。
- Web typecheck、build 通过。
- IMP-F3-001 的双工具协议、状态机、长面基线签名按变更范围重新核对；本改造不得新增实时工具字段。

## 9. 推进计划表

> 最近更新：2026-09-01  
> 更新规则：开始、完成、设计偏差或外部阻塞都立即回写；`Verified` 必须附命令或运行证据。

| 里程碑 | 状态 | 产物 | 完成判据 | 实际结果 / 调整 |
|---|---|---|---|---|
| M0 根因与开源调研 | ✅ Verified | 代码链、开源样本、Provider 选型 | 能解释截图全部异常；高 Star 门槛不造假 | 已确认三个独立根因；采用高 Star 基础设施的分层思想，不迁移整套框架 |
| M1 Spec 与契约 | ✅ Verified | 本文、题单/语音协议、失败边界 | 文档可独立指导实现 | 契约、职责边界、接口、失败策略和 DoD 已按实现回写 |
| M2 中文展示层 | ✅ Verified | `language`、canonical/display 分离、本地化校验、测试 | 中文场景不再原样泄漏英文题干 | 20 条混合技术词 fixture 通过；中/英文运行态均按显式语言展示，canonical 未覆盖 |
| M3 简历证据题单 | ✅ Verified | experiences 解析、ResumeAnchor、配额/顺序、grounding、UI 来源 | 实习/项目深挖有据且位于通用题前 | 单测、API 组卷集成测试和真实 Postgres 回滚事务均得到“经历→项目→题库”；浏览器实测 advance 进入带证据标签的简历题 |
| M4 语音 Provider | ✅ Completed | API gateway、CosyVoice/compatible adapter、浏览器优质回退、取消/错误 | mock 上游与 Web 类型/运行验证通过 | 5 条 API 语音用例、5 条浏览器排序用例通过；实测中文音色选择/刷新保留/英文无匹配诚实降级，但未配置真实神经 TTS |
| M5 集成与运行验收 | 🔄 In progress | 全量回归、真实计划抽查、语音真机试听 | §8 全部达到才可 Verified | 软件与长会话验收已达标；只剩“配置一个真实神经 Provider 并完成 3 句真机试听”，当前 API 明确报告 `disabled/browser` |

状态含义：`⏳ Pending` 未开始；`🔄 In progress` 正在实施；`✅ Completed` 代码和静态测试完成；`✅ Verified` 运行验收完成；`⛔ Blocked` 已记录外部依赖。

### 9.1 当前验收快照

| 证据 | 结果 | 说明 |
|---|---:|---|
| API 回归 | 96 passed | 93 项标准 pytest + 3 项 `tmp_path` 用例独立复验；Windows 沙箱 ACL 不计业务失败 |
| 真实 DB 组卷 smoke | PASS | 在 22,812 道题的 Postgres 上以回滚事务注入合成简历，返回 `resume,resume,bank,bank`、`experience/project` grounding，两道题库 canonical 均保留；未向外部模型发送本地题库 |
| API 改动范围 lint | PASS | Ruff 改动文件通过；FastAPI 项目既有 `Depends/File` 风格按仓库约定忽略 B008 |
| Agents | 27/27 + typecheck/build PASS | 包含题单、grounding、单问题输出闸门和 F4 隔离回归 |
| 真实模型决策集 | 50/50 | 准确率/覆盖率/probe recall=100%，false probe=0，一次可观测重试 |
| 性能对照 | PASS | 一步协议 p50 为旧路径 1.008 倍，低于 2.2 倍门槛 |
| 30 分钟长面 | PASS | 30.4 分钟、9 条追问链、18/18 决策覆盖、0 protocol error、正常 closing |
| 追问人工审计 | 9/9 | 全部承接当前 target 和回答缺口，且候选人可见回复只有一个主问题 |
| Web | 5/5 + typecheck PASS | 最新生产构建已完成编译；后续 TypeScript worker 在受限沙箱被 `spawn EPERM` 中断，同一功能实现的早一次完整构建已通过 |
| 浏览器运行态 | PASS（单浏览器） | 中文证据题、3 个中文系统音色、选择刷新保留、英文无匹配降级、布局和控制台均无异常；Chrome/Edge/Safari/Firefox 实机矩阵未冒充验证 |

## 10. 调整记录

| 日期 | 发现 | 调整 | 影响 |
|---|---|---|---|
| 2026-09-01 | IMP-F3-001 的“下一题由 Harness 原样发布”保证了状态正确，却让英文题干直接进入中文面试 | 新增 `display_stem`，不允许实时模型临场改题 | 保留确定性，同时把语言质量独立出来 |
| 2026-09-01 | `exam_tags` 只能证明“题目相关”，不能证明“在问候选人的真实经历” | 简历声明成为独立题源并携带 grounding | 项目/实习深挖可审计 |
| 2026-09-01 | 专用开源面试项目未达到用户要求的 1k stars | 只把它们当弱样本；架构依据改用 10k+ 语音 Agent 框架和 20k+ 中文 TTS | 避免 Star 背书失真 |
| 2026-09-01 | 高自然度 TTS 需要 GPU 服务或第三方密钥，浏览器无法保证统一音色 | 先实现 Provider 协议和高质量本地回退；真实音色试听单列验收 | 代码完成不等于声音已经 Verified |
| 2026-09-01 | 不同浏览器/系统返回的 locale、音色名称和加载时机不一致 | 使用 `zh/cmn/en` locale 归一化、语言优先的弱启发式排序、`voiceschanged`+有限重试、按语言保存用户选择 | 不依赖特定厂商名；无匹配时不伪装成优质音色 |
| 2026-09-01 | 当前真机只提供 Huihui/Kangkang/Yaoyao 三个标准系统音色，没有 Natural/Neural | UI 允许选择和即时试听，但不将它们标为神经音色；高质量承诺交给服务端 Provider | 浏览器泛化问题已解决，当前设备音色上限仍不可由 Web 代码凭空提升 |
| 2026-09-01 | 实模偶发返回复合多问，只靠 Prompt 无法作为产品边界 | Harness 在发布前只保留第一个完整问题，错语言/空文本则使用目标语言安全问句并留审计事件 | 不增加模型必填字段，同时保证交互只出现一个主问题 |
| 2026-09-01 | 音色选择器与输入/评分按钮同行时会挤压布局 | 音色选择拆成独立行，输入操作区保持可换行 | 1280×720 运行态截图中评分报告不再竖排，输入框和语音按钮可用 |

## 11. 完成定义

只有以下条件同时满足，本文状态才可改为 `Verified`：

1. 中文/英文场景由显式 `language` 决定；中文题的候选人可见表达通过语言 fixture。
2. 题库 canonical stem 未被覆盖，所有 UI/SSE/历史恢复使用 display stem。
3. 简历同时含实习和项目时，题单实际覆盖两类且每题有证据锚点。
4. 实时模型仍只输出 `probe_answer.question` 或零参数 `advance_question`。
5. 神经 TTS adapter、浏览器回退、取消和失败可见性通过自动化。
6. 至少一个真实神经 TTS Provider 完成真机试听；没有外部服务时只能标记 M4 Completed、M5 Blocked/Pending。
7. Agents、API、Web 全量回归通过，F4/answer 不受影响。
