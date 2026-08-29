/** 面试域类型（spec F3）。 */

export type SessionMode = "mock" | "grill" | "answer";

export type Phase =
  | "opening"
  | "self_intro"
  | "project"
  | "knowledge"
  | "scenario"
  | "reverse"
  | "closing";

export interface PersonaConfig {
  /** 目标公司（用于风格与频率榜），如 "字节" */
  company?: string;
  role: string;
  /** 追问风格描述，如 "阿里系：追问多 Agent 协作与 RAG 实现细节" */
  style?: string;
  /** 目标 JD 原文（可选） */
  jd?: string;
  /** 候选人简历要点（可选，I1 阶段由 api 押题注入） */
  resumeHighlights?: string[];
}

/** 组卷题单中的一道题（来自 api /api/interview/plan）。 */
export interface PlanQuestion {
  id: number;
  stem: string;
  kind: string;
  answer: string | null;
}

export interface SessionConfig {
  mode: SessionMode;
  persona: PersonaConfig;
  /** 每阶段最多提问数，超过则推进状态机（仅无题单模式生效） */
  maxQuestionsPerPhase: number;
  /** 追问链最大深度（4 级提示降级，spec F3） */
  maxFollowUpDepth: number;
  /** 题单驱动模式：提供后按题单顺序出题，忽略阶段预算 */
  questions?: PlanQuestion[];
}

export interface PhaseState {
  phase: Phase;
  questionsInPhase: number;
  followUpDepth: number;
}

export interface TurnOutcome {
  reply: string;
  phase: Phase;
  followUpDepth: number;
  phaseAdvanced: boolean;
}

/** SSE 事件协议（web 消费）。 */
export type ClientEvent =
  | { type: "text_delta"; delta: string }
  | { type: "phase"; phase: Phase }
  | { type: "followup"; level: number }
  | { type: "question"; index: number; total: number; stem: string; kind: string }
  | { type: "final"; outcome: TurnOutcome }
  | { type: "error"; message: string };
