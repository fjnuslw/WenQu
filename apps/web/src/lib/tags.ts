/** 题库受控词表（与 apps/api TAG_FAMILIES 同源，spec §3）。 */

export const TAG_FAMILIES = [
  "LLM基础",
  "Transformer",
  "训练与微调",
  "RAG",
  "Agent",
  "MCP与工具调用",
  "多智能体",
  "推理部署",
  "评测",
  "手撕代码",
  "场景设计",
  "HR面",
] as const;

export type TagFamily = (typeof TAG_FAMILIES)[number];

export const QUESTION_KINDS = [
  { value: "knowledge", label: "知识八股" },
  { value: "handwritten_code", label: "手撕代码" },
  { value: "algorithm", label: "算法题" },
  { value: "scenario", label: "场景设计" },
  { value: "behavior", label: "行为面" },
] as const;

export const KIND_LABELS: Record<string, string> = Object.fromEntries(
  QUESTION_KINDS.map(({ value, label }) => [value, label]),
);
