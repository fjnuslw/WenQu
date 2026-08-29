/**
 * 面试流程状态机（spec F3）。
 * 阶段顺序与"阶段预算"是确定性的纯逻辑；"什么时候追问"由 LLM 判断，
 * 但追问深度上限、推进条件由这里硬约束 —— 保证面试一定收敛。
 */

import type { Phase, PhaseState, SessionConfig } from "./types.js";

export const PHASE_ORDER: readonly Phase[] = [
  "opening",
  "self_intro",
  "project",
  "knowledge",
  "scenario",
  "reverse",
  "closing",
] as const;

export function initialState(): PhaseState {
  return { phase: "opening", questionsInPhase: 0, followUpDepth: 0 };
}

export function nextPhase(phase: Phase): Phase {
  const index = PHASE_ORDER.indexOf(phase);
  const next = PHASE_ORDER[index + 1];
  if (!next) throw new Error(`阶段 ${phase} 之后没有下一阶段（状态机越界）`);
  return next;
}

/** 候选人每答完一轮：本阶段问题数 +1，追问深度归零。 */
export function onQuestionCompleted(state: PhaseState): PhaseState {
  return { ...state, questionsInPhase: state.questionsInPhase + 1, followUpDepth: 0 };
}

/** 候选人回答含糊被追问：深度 +1，不累计阶段问题数。 */
export function onFollowUp(state: PhaseState, config: SessionConfig): PhaseState | null {
  if (state.followUpDepth >= config.maxFollowUpDepth) return null; // 追问链打满：标记盲区并换题
  return { ...state, followUpDepth: state.followUpDepth + 1 };
}

/** 是否推进到下一阶段：阶段预算用尽（closing 由 LLM 收尾信号触发）。 */
export function shouldAdvance(state: PhaseState, config: SessionConfig): boolean {
  if (state.phase === "closing") return false;
  return state.questionsInPhase >= config.maxQuestionsPerPhase;
}
