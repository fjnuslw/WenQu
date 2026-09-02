import type { PlanQuestion } from "../types.js";
import type {
  AppliedInterviewDecision,
  InterviewDecisionRecord,
  InterviewDomainEvent,
  InterviewRuntimeState,
  InterviewStateTransitionRecord,
} from "./contracts.js";

function currentQuestionId(state: InterviewRuntimeState, questions: readonly PlanQuestion[]): number | null {
  if (state.currentTarget?.kind !== "plan_question") return null;
  return questions[state.currentTarget.index]?.id ?? null;
}

export function decisionEvents(
  decision: AppliedInterviewDecision,
  questions: readonly PlanQuestion[],
): [InterviewDecisionRecord, InterviewStateTransitionRecord] {
  const decisionRecord: InterviewDecisionRecord = {
    type: "interview_decision",
    turnNo: decision.after.turnNo,
    requestedAction: decision.requestedAction,
    appliedAction: decision.appliedAction,
    ...(decision.followUpQuestion ? { followUpQuestion: decision.followUpQuestion } : {}),
    questionId: currentQuestionId(decision.before, questions),
    depthBefore: decision.before.followUpDepth,
    depthAfter: decision.after.followUpDepth,
    forcedByPolicy: decision.forcedByPolicy,
    ...(decision.reasonCode ? { reasonCode: decision.reasonCode } : {}),
  };
  const transitionRecord: InterviewStateTransitionRecord = {
    type: "state_transition",
    turnNo: decision.after.turnNo,
    before: decision.before,
    after: decision.after,
    reason: decision.reasonCode ?? decision.appliedAction,
  };
  return [decisionRecord, transitionRecord];
}

/** append-only state_transition 事件的最小重放投影。 */
export function replayInterviewState(
  initial: InterviewRuntimeState,
  events: readonly InterviewDomainEvent[],
): InterviewRuntimeState {
  return events.reduce(
    (state, event) => (event.type === "state_transition" ? event.after : state),
    initial,
  );
}
