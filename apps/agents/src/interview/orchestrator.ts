import type { Agent } from "@earendil-works/pi-agent-core";

import type { ClientEvent, PhaseState, PlanQuestion, SessionConfig, TurnOutcome } from "../types.js";
import type {
  AppliedInterviewDecision,
  InterviewRuntimeState,
  RequestedInterviewDecision,
} from "./contracts.js";
import { decisionEvents } from "./events.js";
import { applyInterviewDecision } from "./policy.js";
import { candidateQuestionStem, validateCandidateFollowUp } from "./question-plan.js";
import {
  DECISION_PROTOCOL_CORRECTION,
  decisionTurnDirective,
  deterministicReply,
  interviewFirstTurnContextDirective,
} from "./prompts.js";
import { withNextTurn } from "./state-machine.js";

export class DecisionAlreadyCommitted extends Error {
  constructor() {
    super("本轮控制动作已经提交，不能重复推进状态");
    this.name = "DecisionAlreadyCommitted";
  }
}

/** 单轮 exactly-once 闩锁；业务状态只能在 commit 回调内修改一次。 */
export class InterviewTurnDecisionLatch {
  private value: AppliedInterviewDecision | null = null;
  private claimed = false;

  get committed(): boolean {
    return this.value !== null;
  }

  get inUse(): boolean {
    return this.claimed || this.committed;
  }

  get decision(): AppliedInterviewDecision | null {
    return this.value;
  }

  /** 在任何异步日志 I/O 之前同步占位，避免并发工具调用同时越过检查。 */
  claim(): void {
    if (this.inUse) throw new DecisionAlreadyCommitted();
    this.claimed = true;
  }

  complete(decision: AppliedInterviewDecision): AppliedInterviewDecision {
    if (!this.claimed || this.value) throw new DecisionAlreadyCommitted();
    this.value = decision;
    this.claimed = false;
    return decision;
  }

  rollback(): void {
    if (!this.value) this.claimed = false;
  }

  commit(apply: () => AppliedInterviewDecision): AppliedInterviewDecision {
    this.claim();
    try {
      return this.complete(apply());
    } catch (error) {
      this.rollback();
      throw error;
    }
  }
}

export class InterviewSessionClosed extends Error {
  constructor(id: string) {
    super(`面试会话已经进入收尾，不能继续提交回答: ${id}`);
    this.name = "InterviewSessionClosed";
  }
}

/**
 * F3 orchestrator 所需的最小宿主面。实现可由内存 session、持久 actor 或测试替身提供，
 * 因而 Prompt、policy 与 transport 可以分别替换。
 */
export interface InterviewTurnHost {
  id: string;
  config: SessionConfig;
  agent: Agent;
  state: PhaseState;
  interviewState: InterviewRuntimeState | null;
  decisionLatch: InterviewTurnDecisionLatch | null;
  outputGate: "open" | "decision_pending";
  suppressedText: string;
  streamBuf: string;
  thinkBuf: string;
  contextInjected: boolean;
  questions: PlanQuestion[];
  sink: ((event: ClientEvent) => void) | null;
}

export interface InterviewTurnDependencies {
  appendLog(entry: Record<string, unknown>): Promise<void>;
  appendLogs(entries: readonly object[]): Promise<void>;
  readAssistantUsage(): Record<string, number> | null;
}

function phaseStateFromInterview(state: InterviewRuntimeState): PhaseState {
  return {
    phase: state.phase,
    questionsInPhase: state.questionsInPhase,
    followUpDepth: state.followUpDepth,
  };
}

/** F3 的单步生命周期：回答 -> 工具动作 -> 持久提交 -> 可见追问/下一题。 */
export async function runInterviewTurn(
  host: InterviewTurnHost,
  input: { text: string },
  sink: (event: ClientEvent) => void,
  dependencies: InterviewTurnDependencies,
): Promise<TurnOutcome> {
  const current = host.interviewState;
  if (!current) throw new Error("F3 v2 状态缺失");
  sink({ type: "phase", phase: current.phase });

  if (current.status !== "active" || current.currentTarget === null) {
    throw new InterviewSessionClosed(host.id);
  }

  const contextInjectedBefore = host.contextInjected;
  try {
    return await runActiveInterviewTurn(host, input, sink, dependencies, current);
  } catch (error) {
    if (!host.decisionLatch?.committed) {
      host.interviewState = current;
      host.state = phaseStateFromInterview(current);
      host.contextInjected = contextInjectedBefore;
    }
    throw error;
  }
}

async function runActiveInterviewTurn(
  host: InterviewTurnHost,
  input: { text: string },
  sink: (event: ClientEvent) => void,
  dependencies: InterviewTurnDependencies,
  current: InterviewRuntimeState,
): Promise<TurnOutcome> {
  const directives: string[] = [];
  if (!host.contextInjected) {
    host.contextInjected = true;
    const contextDirective = interviewFirstTurnContextDirective(host.config.persona);
    if (contextDirective) directives.push(contextDirective);
  }

  const turnState = withNextTurn(current);
  const turnNo = turnState.turnNo;
  host.interviewState = turnState;
  host.state = phaseStateFromInterview(turnState);
  directives.push(decisionTurnDirective(turnState, host.questions));

  host.decisionLatch = new InterviewTurnDecisionLatch();
  host.outputGate = "decision_pending";
  host.suppressedText = "";
  host.streamBuf = "";
  host.thinkBuf = "";

  const prompt = `${directives.join("\n\n")}\n\n候选人发言：${input.text}`;
  await dependencies.appendLog({ type: "user", text: input.text, directives });
  try {
    await host.agent.prompt(prompt);
  } catch (error) {
    await handleModelError(host, current, turnNo, error, dependencies);
  }

  if (!host.decisionLatch.committed) {
    await dependencies.appendLog({
      type: "protocol_error",
      turnNo,
      code: "missing_decision",
      retryable: true,
      message: "模型首个请求未调用控制工具；候选人可见正文已拦截",
    });
    host.suppressedText = "";
    try {
      await host.agent.prompt(DECISION_PROTOCOL_CORRECTION);
    } catch (error) {
      await handleModelError(host, current, turnNo, error, dependencies);
    }
  }

  const decision = host.decisionLatch.decision;
  if (host.suppressedText.trim()) {
    await dependencies.appendLog({
      type: "protocol_error",
      turnNo,
      code: "output_before_decision",
      retryable: false,
      message: "控制工具之外产生了正文，已通过输出闸门丢弃",
    });
  }

  let reply: string;
  if (!decision) {
    await dependencies.appendLog({
      type: "protocol_error",
      turnNo,
      code: "missing_decision",
      retryable: false,
      message: "协议纠错后仍未调用控制工具；状态保持不变",
    });
    host.interviewState = current;
    host.state = phaseStateFromInterview(current);
    reply = deterministicReply(null, host.questions, host.config.persona.interviewLanguage);
  } else {
    reply = deterministicReply(decision, host.questions, host.config.persona.interviewLanguage);
  }
  host.outputGate = "open";
  host.streamBuf = reply;

  const thinking = host.thinkBuf.trim();
  const phaseAdvanced = decision ? decision.before.phase !== decision.after.phase : false;
  const outcome: TurnOutcome = {
    reply,
    thinking,
    phase: host.state.phase,
    followUpDepth: host.state.followUpDepth,
    phaseAdvanced,
  };
  await dependencies.appendLog({
    type: "assistant",
    text: outcome.reply,
    thinking,
    usage: dependencies.readAssistantUsage(),
    state: host.state,
  });
  sink({ type: "text_delta", delta: reply });
  return outcome;
}

/** 控制工具的唯一业务入口：同步占位，批量持久化，再发布内存状态与 SSE。 */
export async function commitInterviewDecision(
  host: InterviewTurnHost,
  request: RequestedInterviewDecision,
  dependencies: Pick<InterviewTurnDependencies, "appendLog" | "appendLogs">,
): Promise<{ decision: AppliedInterviewDecision }> {
  const state = host.interviewState;
  const latch = host.decisionLatch;
  if (!state || !latch) throw new Error("当前没有待提交的面试决策");
  if (latch.inUse) {
    await dependencies.appendLog({
      type: "protocol_error",
      turnNo: state.turnNo,
      code: "duplicate_decision",
      retryable: false,
      message: "同一候选人轮次重复调用控制工具；仅首次动作可提交",
    });
    throw new Error("本轮控制动作已经提交，不能重复调用");
  }

  // 必须在首个 await 前同步占位，避免并发工具调用同时越过 committed 检查。
  latch.claim();
  let decision: AppliedInterviewDecision;
  try {
    let validatedRequest: RequestedInterviewDecision = request;
    if (request.action === "probe") {
      const language = host.config.persona.interviewLanguage ?? "zh-CN";
      let followUpQuestion: string;
      let adjustment: string | null = null;
      try {
        followUpQuestion = validateCandidateFollowUp(request.followUpQuestion, language);
        if (followUpQuestion !== request.followUpQuestion.trim()) {
          adjustment = "模型串联了多个候选人可见问题；Harness 只保留第一问";
        }
      } catch (error) {
        adjustment = error instanceof Error ? error.message : String(error);
        followUpQuestion =
          language === "en-US"
            ? "Choose the single most important point from your answer. What did you personally do, and why?"
            : "请只选你刚才回答中最关键的一项，具体说明你本人怎么做以及为什么这样做？";
      }
      if (adjustment) {
        await dependencies.appendLog({
          type: "protocol_error",
          turnNo: state.turnNo,
          code: "invalid_decision",
          retryable: false,
          message: adjustment,
        });
      }
      validatedRequest = { action: "probe", followUpQuestion };
    }
    decision = applyInterviewDecision({
      state,
      request: validatedRequest,
      questions: host.questions,
      maxFollowUpDepth: host.config.maxFollowUpDepth,
    });
    await dependencies.appendLogs(decisionEvents(decision, host.questions));
    latch.complete(decision);
  } catch (error) {
    latch.rollback();
    throw error;
  }

  host.interviewState = decision.after;
  host.state = phaseStateFromInterview(decision.after);
  host.sink?.({
    type: "decision",
    action: decision.appliedAction,
    followUpDepth: host.state.followUpDepth,
    forced: decision.forcedByPolicy,
  });
  host.sink?.({ type: "phase", phase: host.state.phase });
  if (decision.appliedAction === "probe") {
    host.sink?.({ type: "followup", level: host.state.followUpDepth });
  } else if (decision.introducedQuestionIndex !== null && decision.introducedQuestionIndex !== undefined) {
    const question = host.questions[decision.introducedQuestionIndex];
    if (!question) throw new Error(`下一题索引越界: ${decision.introducedQuestionIndex}`);
    host.sink?.({
      type: "question",
      index: decision.introducedQuestionIndex + 1,
      total: host.questions.length,
      stem: candidateQuestionStem(question),
      kind: question.kind,
      source: question.source ?? "bank",
      ...(question.grounding?.label ? { groundingLabel: question.grounding.label } : {}),
    });
  }
  return { decision };
}

async function handleModelError(
  host: InterviewTurnHost,
  beforeTurn: InterviewRuntimeState,
  turnNo: number,
  error: unknown,
  dependencies: Pick<InterviewTurnDependencies, "appendLog">,
): Promise<void> {
  const decision = host.decisionLatch?.decision ?? null;
  await dependencies.appendLog({
    type: "protocol_error",
    turnNo,
    code: "model_error",
    retryable: !decision,
    message: error instanceof Error ? error.message : String(error),
  });
  if (decision) return;
  host.interviewState = beforeTurn;
  host.state = phaseStateFromInterview(beforeTurn);
  throw error;
}
