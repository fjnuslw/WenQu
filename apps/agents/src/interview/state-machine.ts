import type { PlanQuestion } from "../types.js";
import type { InterviewRuntimeState } from "./contracts.js";

export function phaseForQuestionKind(kind: string): InterviewRuntimeState["phase"] {
  if (kind === "scenario") return "scenario";
  if (kind === "project" || kind === "experience") return "project";
  return "knowledge";
}

/** mock 会话从候选人的自我介绍开始；题单第一题尚未引入。 */
export function initialInterviewState(): InterviewRuntimeState {
  return {
    status: "active",
    phase: "self_intro",
    currentTarget: { kind: "self_intro" },
    questionsInPhase: 0,
    followUpDepth: 0,
    turnNo: 0,
  };
}

export function withNextTurn(state: InterviewRuntimeState): InterviewRuntimeState {
  return { ...state, turnNo: state.turnNo + 1 };
}

export function transitionProbe(state: InterviewRuntimeState): InterviewRuntimeState {
  if (state.status !== "active" || state.currentTarget === null) {
    throw new Error(`当前状态不能追问: ${state.status}/${state.phase}`);
  }
  return {
    ...state,
    followUpDepth: state.followUpDepth + 1,
  };
}

export interface AdvanceTransition {
  state: InterviewRuntimeState;
  introducedQuestionIndex: number | null;
}

/**
 * 推进由题单唯一决定：self_intro -> 第 1 题；第 N 题 -> 第 N+1 题；
 * 末题之后进入 closing。模型不能自行指定题号或结束状态。
 */
export function transitionAdvance(
  state: InterviewRuntimeState,
  questions: readonly PlanQuestion[],
): AdvanceTransition {
  if (state.status !== "active" || state.currentTarget === null) {
    throw new Error(`当前状态不能推进: ${state.status}/${state.phase}`);
  }

  const nextIndex = state.currentTarget.kind === "plan_question" ? state.currentTarget.index + 1 : 0;
  const nextQuestion = questions[nextIndex];
  if (!nextQuestion) {
    return {
      state: {
        ...state,
        status: "closing",
        phase: "closing",
        currentTarget: null,
        followUpDepth: 0,
      },
      introducedQuestionIndex: null,
    };
  }

  const nextPhase = phaseForQuestionKind(nextQuestion.kind);
  const staysInPhase = state.currentTarget.kind === "plan_question" && state.phase === nextPhase;

  return {
    state: {
      ...state,
      phase: nextPhase,
      currentTarget: { kind: "plan_question", index: nextIndex },
      questionsInPhase: staysInPhase ? state.questionsInPhase + 1 : 1,
      followUpDepth: 0,
    },
    introducedQuestionIndex: nextIndex,
  };
}
