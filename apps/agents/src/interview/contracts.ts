import type { Phase } from "../types.js";

export type InterviewDecisionAction = "probe" | "advance";

/** 候选人当前正在回应的对象。运行时状态，不暴露为模型输出 schema。 */
export type InterviewTarget =
  | { kind: "self_intro" }
  | { kind: "plan_question"; index: number }
  | { kind: "reverse" };

export interface InterviewRuntimeState {
  status: "active" | "closing" | "finished";
  phase: Phase;
  currentTarget: InterviewTarget | null;
  questionsInPhase: number;
  followUpDepth: number;
  turnNo: number;
}

export type InterviewDecisionReasonCode = "followup_cap" | "protocol_fallback";

export type RequestedInterviewDecision =
  | {
      action: "probe";
      /** 唯一的自由文本字段：将直接作为候选人可见追问，不是分析表或状态。 */
      followUpQuestion: string;
    }
  | { action: "advance" };

export interface AppliedInterviewDecision {
  requestedAction: InterviewDecisionAction;
  appliedAction: InterviewDecisionAction;
  followUpQuestion?: string;
  before: InterviewRuntimeState;
  after: InterviewRuntimeState;
  forcedByPolicy: boolean;
  reasonCode?: InterviewDecisionReasonCode;
  /** advance 后引入的题单索引；null 表示进入 closing。 */
  introducedQuestionIndex?: number | null;
}

export interface InterviewDecisionRecord {
  type: "interview_decision";
  turnNo: number;
  requestedAction: InterviewDecisionAction;
  appliedAction: InterviewDecisionAction;
  followUpQuestion?: string;
  questionId: number | null;
  depthBefore: number;
  depthAfter: number;
  forcedByPolicy: boolean;
  reasonCode?: InterviewDecisionReasonCode;
}

export interface InterviewStateTransitionRecord {
  type: "state_transition";
  turnNo: number;
  before: InterviewRuntimeState;
  after: InterviewRuntimeState;
  reason: InterviewDecisionAction | InterviewDecisionReasonCode;
}

export interface InterviewProtocolErrorRecord {
  type: "protocol_error";
  turnNo: number;
  code:
    | "missing_decision"
    | "duplicate_decision"
    | "invalid_decision"
    | "model_error"
    | "output_before_decision"
    | "missing_reply";
  retryable: boolean;
  message: string;
}

export type InterviewDomainEvent =
  | InterviewDecisionRecord
  | InterviewStateTransitionRecord
  | InterviewProtocolErrorRecord;
