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
  /** api 组卷官生成的本场考察简报（画像+考察重点，给面试官不念给候选人） */
  brief?: string;
  /** 候选人简历要点（I1：api 简历解析管道产出） */
  resumeHighlights?: string[];
}

/** 组卷题单中的一道题（来自 api /api/interview/plan）。 */
export interface PlanQuestion {
  id: number;
  stem: string;
  kind: string;
  answer: string | null;
  /** 该公司真实面经的追问素材（api 从 experience_items 检索，面试官择用） */
  probes?: string[];
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
  /** 项目拷打模式（G1）：临时仓库与备课产物 */
  grill?: GrillContext;
}

export interface GrillContext {
  projectId: number;
  projectName: string;
  /** 临时仓库根目录（路径监狱的锚点，agents 直接读共享 data 目录） */
  repoRoot: string;
  /** 备课简报（api 备课管道产出：overview/stack/modules 含拷打题） */
  briefing: {
    overview: string;
    stack_summary: string;
    modules: {
      files: string[];
      purpose: string;
      tech_points: string[];
      detail_questions: string[];
      alternative_question?: string | null;
      missing_question?: string | null;
    }[];
  };
  /** 简历声明对照结论（可选）：拷打官的质证弹药 */
  claimChecks?: {
    claim: string;
    status: string;
    evidence?: string | null;
    probe_question: string;
  }[];
  /** 题库相关题（可选）：api 按 exam_tags 检索的拷打弹药 */
  bankQuestions?: string[];
  /** 该公司面经追问素材（可选） */
  experienceProbes?: string[];
}

export interface PhaseState {
  phase: Phase;
  questionsInPhase: number;
  followUpDepth: number;
}

export interface TurnOutcome {
  reply: string;
  /** 本轮思考流全文（thinkingLevel 开启时），供日志与 UI 复盘 */
  thinking: string;
  phase: Phase;
  followUpDepth: number;
  phaseAdvanced: boolean;
}

/** SSE 事件协议（web 消费）。 */
export type ClientEvent =
  | { type: "text_delta"; delta: string }
  | { type: "thinking_delta"; delta: string }
  | { type: "phase"; phase: Phase }
  | { type: "followup"; level: number }
  | { type: "question"; index: number; total: number; stem: string; kind: string }
  | { type: "final"; outcome: TurnOutcome }
  | { type: "error"; message: string };
