/** 面试阶段展示用（与 apps/agents/src/state-machine.ts 的 PHASE_ORDER 保持同步）。 */

export const INTERVIEW_PHASES = [
  { id: "opening", label: "开场" },
  { id: "self_intro", label: "自我介绍" },
  { id: "project", label: "项目深挖" },
  { id: "knowledge", label: "知识八股" },
  { id: "scenario", label: "场景设计" },
  { id: "reverse", label: "反问" },
  { id: "closing", label: "收尾" },
] as const;

export type PhaseId = (typeof INTERVIEW_PHASES)[number]["id"];
