/**
 * 会话管理：pi Agent 生命周期 + JSONL append-only 日志（spec §5.2）。
 * 状态只存在内存 + 日志文件；评分报告由 apps/api 读取日志生成（职责分离）。
 *
 * F3 题单面试由模型通过最小控制工具请求 probe/advance，Harness 校验并提交状态；
 * 题号、深度、结束条件与日志不由模型填写。其他模式继续复用既有瘦循环。
 */

import { randomUUID } from "node:crypto";
import { mkdir, appendFile } from "node:fs/promises";
import path from "node:path";

import type { Agent } from "@earendil-works/pi-agent-core";

import type { AgentServiceConfig } from "./config.js";
import {
  buildInterviewControlTools,
  candidateQuestionStem,
  commitInterviewDecision,
  initialInterviewState,
  interviewSystemPrompt,
  runInterviewTurn,
  type InterviewRuntimeState,
  type InterviewTurnHost,
} from "./interview/index.js";
import type { PiRuntime } from "./pi.js";
import { webSearchTool } from "./tools/web-search.js";
import { initialState, nextPhase, onQuestionCompleted, shouldAdvance } from "./state-machine.js";
import {
  firstTurnContextDirective,
  grillFirstTurnDirective,
  grillSystemPrompt,
  phaseDirective,
  systemPrompt,
} from "./prompts.js";
import { buildGrillTools } from "./tools/grill-repo.js";
import type { ClientEvent, PhaseState, PlanQuestion, SessionConfig, TurnOutcome } from "./types.js";

interface RunningSession extends InterviewTurnHost {
  /** 单会话只允许一个候选人轮次在飞，避免并发请求覆盖 sink/latch。 */
  turnInFlight: boolean;
  /** legacy 题单路径游标；F3 v2 使用规范 currentTarget。 */
  qIndex: number;
  logPath: string;
  /** 串行化同一会话的 append，避免 agent 事件与领域提交互相穿插。 */
  logTail: Promise<void>;
}

export interface TurnInput {
  text: string;
}

/** 类型化错误：服务层映射为 404，不做字符串匹配。 */
export class SessionNotFound extends Error {
  constructor(id: string) {
    super(`会话不存在或已过期: ${id}`);
    this.name = "SessionNotFound";
  }
}

export class SessionTurnInProgress extends Error {
  constructor(id: string) {
    super(`会话已有一轮正在处理，请等待完成后再提交: ${id}`);
    this.name = "SessionTurnInProgress";
  }
}

/** 从 pi 消息对象中稳健取文本（内容可能是 string 或块数组）。 */
function messageText(message: unknown): string {
  if (typeof message === "string") return message;
  if (message && typeof message === "object" && "content" in message) {
    const content = (message as { content: unknown }).content;
    if (typeof content === "string") return content;
    if (Array.isArray(content)) {
      return content
        .map((block) =>
          block && typeof block === "object" && "text" in block
            ? String((block as { text: unknown }).text)
            : "",
        )
        .join("");
    }
  }
  return "";
}

/**
 * 已知失败模式的确定性清理：模型偶尔会把注入的 [导演指令] 原样回声给候选人。
 * 按我们自己注入的标记做裁剪（不改写其余内容），并非掩盖语义错误。
 */
function stripEchoedDirective(text: string): string {
  if (!text.startsWith("[导演指令]")) return text;
  const marker = "候选人发言：";
  const idx = text.indexOf(marker);
  if (idx !== -1) return text.slice(idx + marker.length).trim();
  const firstBreak = text.indexOf("\n\n");
  return firstBreak === -1 ? text : text.slice(firstBreak).trim();
}

/** 题型 → 展示阶段映射（题单驱动模式）。 */
function phaseForKind(kind: string): PhaseState["phase"] {
  if (kind === "scenario") return "scenario";
  if (kind === "project" || kind === "experience") return "project";
  return "knowledge";
}

function questionDirective(index: number, total: number, q: PlanQuestion): string {
  const answer = q.answer ?? "（无参考要点，按你的知识判断回答质量）";
  const probes = q.probes?.length
    ? `\n追问素材（来自该公司真实面经，提问后择用——改写成你的追问，不相关就不用）：\n${q.probes
        .map((probe) => `- ${probe}`)
        .join("\n")}`
    : "";
  return [
    `[导演指令] 现在提出题单第 ${index}/${total} 题。`,
    `题干：${candidateQuestionStem(q)}`,
    `参考答案要点（仅供你判断回答质量与追问方向，切勿直接念给候选人）：${answer}`,
    probes,
  ]
    .filter((part) => part !== "")
    .join("\n");
}

export class SessionManager {
  private readonly sessions = new Map<string, RunningSession>();

  constructor(
    private readonly runtime: PiRuntime,
    private readonly config: AgentServiceConfig,
  ) {}

  async create(config: SessionConfig): Promise<string> {
    const id = randomUUID();
    await mkdir(this.config.dataDir, { recursive: true });
    const logPath = path.join(this.config.dataDir, `${id}.jsonl`);
    const questions = config.questions ?? [];
    if (config.mode === "mock" && questions.length === 0) {
      throw new Error("mode=mock 必须提供非空题单（F3 v2 不支持无题单 legacy 模式）");
    }
    const usesInterviewV2 = config.mode === "mock";
    const interviewState = usesInterviewV2 ? initialInterviewState() : null;
    // 思考档位按模式分档：答题（mode=answer）吃满全局档（max）——深度推理是产品特性；
    // 面试官短回复用 medium 即可，省下 reasoning token 开销。
    const thinkingLevel =
      config.mode === "answer" ? this.config.thinkingLevel : config.mode === "grill" ? "high" : "medium";
    let agent: Agent;
    let sessionRef: RunningSession | null = null;
    if (config.mode === "grill" && config.grill) {
      // 项目拷打（G1）：只读工具面（路径监狱锚定临时仓库根），备课产物经首轮指令注入
      const tools = buildGrillTools(config.grill.repoRoot, {
        projectId: config.grill.projectId,
        apiBaseUrl: this.config.apiBaseUrl,
        capabilities: config.grill.capabilities,
      });
      agent = this.runtime.agentFactory(
        grillSystemPrompt(
          config.maxFollowUpDepth,
          tools.all.map((tool) => tool.name),
        ),
        tools.all,
        thinkingLevel,
        id,
      );
    } else if (usesInterviewV2) {
      const controlTools = buildInterviewControlTools(async (request) => {
        if (!sessionRef) throw new Error("面试会话尚未完成初始化");
        return await commitInterviewDecision(sessionRef, request, {
          appendLog: async (entry) => await this.appendLog(sessionRef as RunningSession, entry),
          appendLogs: async (entries) => await this.appendLogs(sessionRef as RunningSession, entries),
        });
      });
      agent = this.runtime.agentFactory(interviewSystemPrompt(), controlTools, thinkingLevel, id);
    } else {
      agent = this.runtime.agentFactory(
        systemPrompt(config),
        config.mode === "answer" ? [webSearchTool] : undefined,
        thinkingLevel,
        id,
      );
    }
    const session: RunningSession = {
      id,
      config,
      agent,
      state: interviewState
        ? {
            phase: interviewState.phase,
            questionsInPhase: interviewState.questionsInPhase,
            followUpDepth: interviewState.followUpDepth,
          }
        : initialState(),
      interviewState,
      decisionLatch: null,
      turnInFlight: false,
      outputGate: "open",
      suppressedText: "",
      sink: null,
      logPath,
      logTail: Promise.resolve(),
      questions,
      qIndex: 0,
      streamBuf: "",
      thinkBuf: "",
      contextInjected: false,
    };
    sessionRef = session;
    agent.subscribe((event: unknown) => this.onAgentEvent(session, event));
    await this.appendLog(session, {
      type: "session_start",
      config,
      runtime: {
        model: this.config.defaultModel,
        thinkingLevel,
        protocolVersion: usesInterviewV2 ? "f3.v2.one_step_question_arg" : "legacy",
      },
    });
    this.sessions.set(id, session);
    return id;
  }

  require(id: string): RunningSession {
    const session = this.sessions.get(id);
    if (!session) throw new SessionNotFound(id);
    return session;
  }

  snapshot(id: string): {
    id: string;
    phase: string;
    questionsInPhase: number;
    followUpDepth: number;
    status?: InterviewRuntimeState["status"];
    currentTarget?: InterviewRuntimeState["currentTarget"];
    turnNo?: number;
  } {
    const session = this.require(id);
    return {
      id,
      ...session.state,
      ...(session.interviewState
        ? {
            status: session.interviewState.status,
            currentTarget: session.interviewState.currentTarget,
            turnNo: session.interviewState.turnNo,
          }
        : {}),
    };
  }

  /** 处理候选人一轮发言：状态机/题单推进 → 导演指令 → pi Agent → 落盘。 */
  async turn(id: string, input: TurnInput, sink: (event: ClientEvent) => void): Promise<TurnOutcome> {
    const session = this.require(id);
    if (session.turnInFlight) throw new SessionTurnInProgress(id);
    session.turnInFlight = true;
    session.sink = sink;
    try {
      if (session.interviewState) {
        return await runInterviewTurn(session, input, sink, {
          appendLog: async (entry) => await this.appendLog(session, entry),
          appendLogs: async (entries) => await this.appendLogs(session, entries),
          readAssistantUsage: () => this.lastAssistantUsage(session),
        });
      }
      return await this.turnLegacy(session, input, sink);
    } finally {
      session.sink = null;
      session.decisionLatch = null;
      session.outputGate = "open";
      session.turnInFlight = false;
    }
  }

  /** F4/answer 的既有瘦循环；与 F3 领域编排保持隔离。 */
  private async turnLegacy(
    session: RunningSession,
    input: TurnInput,
    sink: (event: ClientEvent) => void,
  ): Promise<TurnOutcome> {
    sink({ type: "phase", phase: session.state.phase });

    const directives: string[] = [];
    let phaseAdvanced = false;

    // 首轮注入简报/简历要点（仅一次，随后进入可缓存前缀——跨会话缓存的取舍见 prompts.ts）
    if (!session.contextInjected) {
      session.contextInjected = true;
      const contextDirective =
        session.config.mode === "grill" && session.config.grill
          ? grillFirstTurnDirective(session.config.grill)
          : firstTurnContextDirective(session.config.persona);
      if (contextDirective) directives.push(contextDirective);
    }

    if (session.questions.length > 0) {
      // v2 只用于 mode=mock；其他模式若意外携带题单，保持原来的顺序出题行为。
      const q = session.questions[session.qIndex];
      if (q === undefined) {
        session.state = { ...session.state, phase: "closing", followUpDepth: 0 };
        sink({ type: "phase", phase: "closing" });
        directives.push("[导演指令] 题单已全部完成，请做总结收尾，不再提出新问题。");
      } else {
        session.qIndex += 1;
        session.state = {
          ...session.state,
          phase: phaseForKind(q.kind),
          followUpDepth: 0,
        };
        sink({ type: "phase", phase: session.state.phase });
        sink({
          type: "question",
          index: session.qIndex,
          total: session.questions.length,
          stem: candidateQuestionStem(q),
          kind: q.kind,
        });
        directives.push(questionDirective(session.qIndex, session.questions.length, q));
      }
    } else {
      session.state = onQuestionCompleted(session.state);
      if (shouldAdvance(session.state, session.config)) {
        const next = nextPhase(session.state.phase);
        session.state = { ...session.state, phase: next, questionsInPhase: 0, followUpDepth: 0 };
        phaseAdvanced = true;
        sink({ type: "phase", phase: next });
      }
      directives.push(phaseDirective(session.state, session.config));
    }

    const prompt = `${directives.join("\n")}\n\n候选人发言：${input.text}`;
    await this.appendLog(session, { type: "user", text: input.text, directives });
    session.streamBuf = "";
    session.thinkBuf = "";
    await session.agent.prompt(prompt);

    const thinking = session.thinkBuf.trim();
    const outcome: TurnOutcome = {
      reply: stripEchoedDirective(this.lastAssistantText(session)),
      thinking,
      phase: session.state.phase,
      followUpDepth: session.state.followUpDepth,
      phaseAdvanced,
    };
    await this.appendLog(session, {
      type: "assistant",
      text: outcome.reply,
      thinking,
      usage: this.lastAssistantUsage(session),
      state: session.state,
    });
    return outcome;
  }

  private async onAgentEvent(session: RunningSession, event: unknown): Promise<void> {
    if (!event || typeof event !== "object") return;
    const typed = event as {
      type?: string;
      toolName?: string;
      assistantMessageEvent?: { type?: string; delta?: string };
    };
    if (typed.type === "tool_execution_start" && typeof typed.toolName === "string") {
      // 所有工具调用均落审计日志；F3 控制工具与 F4 读码工具共用这一事件面。
      await this.appendLog(session, { type: "tool_use", tool: typed.toolName });
      return;
    }
    if (typed.type !== "message_update") return;
    const messageEvent = typed.assistantMessageEvent;
    if (!messageEvent) return;
    if (messageEvent.type === "text_delta" && messageEvent.delta) {
      const delta = messageEvent.delta;
      if (session.outputGate === "decision_pending") {
        session.suppressedText += delta;
        return;
      }
      session.streamBuf += delta; // 累积为 assistant 原文（主数据源）
      session.sink?.({ type: "text_delta", delta });
    }
    if (messageEvent.type === "thinking_delta" && messageEvent.delta) {
      // F3 的审计证据是候选人原话、控制动作、追问与状态转换；隐藏推理
      // 不向候选人展示也不落盘。answer/F4 保留既有教学/查证型思考面板。
      if (session.config.mode === "mock") return;
      const delta = messageEvent.delta;
      session.thinkBuf += delta;
      session.sink?.({ type: "thinking_delta", delta });
    }
  }

  private lastAssistantText(session: RunningSession): string {
    // 首选：流式增量累积（与本轮回声同源、时序无竞态）；agent.state.messages 扫描作为对账
    const streamed = session.streamBuf.trim();
    if (streamed) return streamed;
    const agent = session.agent as unknown as { state?: { messages?: unknown[] } };
    const messages = agent.state?.messages ?? [];
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index] as { role?: string } | null;
      if (message?.role === "assistant") {
        const text = messageText(message).trim();
        if (text) return text;
      }
    }
    throw new Error("本轮未收到 assistant 文本（pi 事件流异常），显式失败而非空回复兜底");
  }

  private lastAssistantUsage(session: RunningSession): Record<string, number> | null {
    // pi Agent 的消息数组经 agent.state.messages 访问（agent.messages 不存在——
    // 正文提取一直由 streamBuf 主路径承担，此处是它的首个真实消费方）
    const agent = session.agent as unknown as { state?: { messages?: unknown[] } };
    const messages = agent.state?.messages ?? [];
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index] as { role?: string; usage?: Record<string, unknown> | null } | null;
      if (message?.role === "assistant") {
        const usage = message.usage;
        if (!usage) return null;
        const pick = (key: string): number => (typeof usage[key] === "number" ? (usage[key] as number) : 0);
        const recorded: Record<string, number> = {
          input: pick("input"),
          output: pick("output"),
          cacheRead: pick("cacheRead"),
          cacheWrite: pick("cacheWrite"),
        };
        if (typeof usage.reasoning === "number") recorded.reasoning = usage.reasoning;
        return recorded;
      }
    }
    return null;
  }

  private async appendLog(session: RunningSession, entry: Record<string, unknown>): Promise<void> {
    await this.appendLogs(session, [entry]);
  }

  /** 同一状态提交关联的事件以单次 append 写入，避免只留下半组 decision/transition。 */
  private async appendLogs(
    session: RunningSession,
    entries: readonly object[],
  ): Promise<void> {
    const payload = entries
      .map((entry) => JSON.stringify({ ts: new Date().toISOString(), ...entry }))
      .join("\n");
    const write = session.logTail.then(async () => {
      await appendFile(session.logPath, `${payload}\n`, "utf8");
    });
    session.logTail = write.catch(() => undefined);
    await write;
  }
}
