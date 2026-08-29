/**
 * 会话管理：pi Agent 生命周期 + JSONL append-only 日志（spec §5.2）。
 * 状态只存在内存 + 日志文件；评分报告由 apps/api 读取日志生成（职责分离）。
 *
 * 回答"含糊与否"的判定是 api 侧评审器（I1）的职责，本服务只消费判定结果
 * 驱动确定性状态机 —— 保证面试一定收敛，不依赖 LLM 自觉。
 */

import { randomUUID } from "node:crypto";
import { mkdir, appendFile } from "node:fs/promises";
import path from "node:path";

import type { Agent } from "@earendil-works/pi-agent-core";

import type { AgentServiceConfig } from "./config.js";
import type { PiRuntime } from "./pi.js";
import { webSearchTool } from "./tools/web-search.js";
import { initialState, nextPhase, onFollowUp, onQuestionCompleted, shouldAdvance } from "./state-machine.js";
import { followUpDirective, phaseDirective, systemPrompt } from "./prompts.js";
import type { ClientEvent, PhaseState, PlanQuestion, SessionConfig, TurnOutcome } from "./types.js";

interface RunningSession {
  id: string;
  config: SessionConfig;
  agent: Agent;
  state: PhaseState;
  /** 题单驱动模式：待出题队列与游标 */
  questions: PlanQuestion[];
  qIndex: number;
  /** 本轮流式增量累积（assistant 原文的第一数据源） */
  streamBuf: string;
  /** 当前轮次的 SSE 下沉点（turn 期间有效） */
  sink: ((event: ClientEvent) => void) | null;
  logPath: string;
}

export interface TurnInput {
  text: string;
  /** 评审器对候选人上一答的判定；缺省视为有效回答（推进问题计数）。 */
  vagueAnswer?: boolean;
}

/** 类型化错误：服务层映射为 404，不做字符串匹配。 */
export class SessionNotFound extends Error {
  constructor(id: string) {
    super(`会话不存在或已过期: ${id}`);
    this.name = "SessionNotFound";
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
  return "knowledge";
}

function questionDirective(index: number, total: number, q: PlanQuestion): string {
  const answer = q.answer ?? "（无参考要点，按你的知识判断回答质量）";
  return [
    `[导演指令] 现在提出题单第 ${index}/${total} 题。`,
    `题干：${q.stem}`,
    `参考答案要点（仅供你判断回答质量与追问方向，切勿直接念给候选人）：${answer}`,
  ].join("\n");
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
    const agent = this.runtime.agentFactory(
      systemPrompt(config),
      config.mode === "answer" ? [webSearchTool] : undefined,
    );
    const questions = config.questions ?? [];
    const session: RunningSession = {
      id,
      config,
      agent,
      state: initialState(),
      sink: null,
      logPath,
      questions,
      qIndex: 0,
      streamBuf: "",
    };
    agent.subscribe((event: unknown) => this.onAgentEvent(session, event));
    this.sessions.set(id, session);
    await this.appendLog(session, { type: "session_start", config });
    return id;
  }

  require(id: string): RunningSession {
    const session = this.sessions.get(id);
    if (!session) throw new SessionNotFound(id);
    return session;
  }

  snapshot(id: string): { id: string; phase: string; questionsInPhase: number; followUpDepth: number } {
    return { id, ...this.require(id).state };
  }

  /** 处理候选人一轮发言：状态机/题单推进 → 导演指令 → pi Agent → 落盘。 */
  async turn(id: string, input: TurnInput, sink: (event: ClientEvent) => void): Promise<TurnOutcome> {
    const session = this.require(id);
    session.sink = sink;
    sink({ type: "phase", phase: session.state.phase });

    const directives: string[] = [];
    let phaseAdvanced = false;

    if (session.questions.length > 0) {
      // ---- 题单驱动模式：队列出题，阶段预算不生效 ----
      // 含糊且追问未打满 → 原题追问（不推进队列）；有效回答或追问打满 → 出下一题
      let introduceNext = true;
      if (input.vagueAnswer === true) {
        const advanced = onFollowUp(session.state, session.config);
        if (advanced) {
          session.state = advanced;
          sink({ type: "followup", level: session.state.followUpDepth });
          directives.push(followUpDirective(session.state));
          introduceNext = false;
        }
        // 追问打满：该题记盲区，introduceNext 保持 true，下方出下一题
      }        if (introduceNext) {
          const q = session.questions[session.qIndex];
          if (q === undefined) throw new Error("题队列耗尽却尝试出题（状态机越界），显式失败");
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
            stem: q.stem,
            kind: q.kind,
          });
          directives.push(questionDirective(session.qIndex, session.questions.length, q));
        } else {
          session.state = { ...session.state, phase: "closing", followUpDepth: 0 };
          sink({ type: "phase", phase: "closing" });
          directives.push("[导演指令] 题单已全部完成，请做总结收尾，不再提出新问题。");
        }
    } else {
      // ---- 无题单：原状态机 ----
      if (input.vagueAnswer === true) {
        const advanced = onFollowUp(session.state, session.config);
        if (advanced) {
          session.state = advanced;
          sink({ type: "followup", level: session.state.followUpDepth });
          directives.push(followUpDirective(session.state));
        } else {
          session.state = onQuestionCompleted(session.state);
        }
      } else {
        session.state = onQuestionCompleted(session.state);
      }
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
    session.streamBuf = ""; // 新一轮清空流式累积
    await session.agent.prompt(prompt);

    const outcome: TurnOutcome = {
      reply: stripEchoedDirective(this.lastAssistantText(session)),
      phase: session.state.phase,
      followUpDepth: session.state.followUpDepth,
      phaseAdvanced,
    };
    await this.appendLog(session, { type: "assistant", text: outcome.reply, state: session.state });
    session.sink = null;
    return outcome;
  }

  private onAgentEvent(session: RunningSession, event: unknown): void {
    if (!event || typeof event !== "object") return;
    const typed = event as { type?: string; assistantMessageEvent?: { type?: string; delta?: string } };
    if (typed.type === "message_update" && typed.assistantMessageEvent?.type === "text_delta") {
      const delta = typed.assistantMessageEvent.delta ?? "";
      if (delta) {
        session.streamBuf += delta; // 累积为 assistant 原文（主数据源）
        session.sink?.({ type: "text_delta", delta });
      }
    }
  }

  private lastAssistantText(session: RunningSession): string {
    // 首选：流式增量累积（与本轮回声同源、时序无竞态）；messages 扫描作为对账
    const streamed = session.streamBuf.trim();
    if (streamed) return streamed;
    const agent = session.agent as unknown as { messages?: unknown[] };
    const messages = agent.messages ?? [];
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index] as { role?: string } | null;
      if (message?.role === "assistant") {
        const text = messageText(message).trim();
        if (text) return text;
      }
    }
    throw new Error("本轮未收到 assistant 文本（pi 事件流异常），显式失败而非空回复兜底");
  }

  private async appendLog(session: RunningSession, entry: Record<string, unknown>): Promise<void> {
    await appendFile(session.logPath, `${JSON.stringify({ ts: new Date().toISOString(), ...entry })}\n`, "utf8");
  }
}
