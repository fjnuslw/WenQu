import type { PlanQuestion } from "../types.js";
import type {
  AppliedInterviewDecision,
  InterviewRuntimeState,
  RequestedInterviewDecision,
} from "./contracts.js";
import { transitionAdvance, transitionProbe } from "./state-machine.js";

export interface ApplyInterviewDecisionInput {
  state: InterviewRuntimeState;
  request: RequestedInterviewDecision;
  questions: readonly PlanQuestion[];
  maxFollowUpDepth: number;
}

/** 只在这里解释深度上限；工具、Prompt 与 Web 不重复实现 policy。 */
export function applyInterviewDecision(input: ApplyInterviewDecisionInput): AppliedInterviewDecision {
  const { state, questions, maxFollowUpDepth } = input;
  let request = input.request;
  if (!Number.isInteger(maxFollowUpDepth) || maxFollowUpDepth < 1) {
    throw new Error(`maxFollowUpDepth 必须是正整数: ${maxFollowUpDepth}`);
  }
  if (state.status !== "active" || state.currentTarget === null) {
    throw new Error(`面试不在可决策状态: ${state.status}/${state.phase}`);
  }

  if (request.action === "probe") {
    const question = request.followUpQuestion.trim();
    if (!question || question.length > 240) {
      throw new Error("probe 的 followUpQuestion 必须为 1..240 字符");
    }
    request = { action: "probe", followUpQuestion: question };
  }

  if (request.action === "probe" && state.followUpDepth < maxFollowUpDepth) {
    return {
      requestedAction: "probe",
      appliedAction: "probe",
      followUpQuestion: request.followUpQuestion,
      before: state,
      after: transitionProbe(state),
      forcedByPolicy: false,
    };
  }

  const advanced = transitionAdvance(state, questions);
  const forcedByPolicy = request.action === "probe";
  return {
    requestedAction: request.action,
    appliedAction: "advance",
    before: state,
    after: advanced.state,
    forcedByPolicy,
    ...(forcedByPolicy ? { reasonCode: "followup_cap" as const } : {}),
    introducedQuestionIndex: advanced.introducedQuestionIndex,
  };
}
