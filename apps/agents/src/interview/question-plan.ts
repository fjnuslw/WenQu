import type { PlanQuestion } from "../types.js";

/** canonical stem 永远用于溯源；候选人只看到组卷阶段校验过的 displayStem。 */
export function candidateQuestionStem(question: PlanQuestion): string {
  return question.displayStem?.trim() || question.stem;
}

export function groundingDirective(question: PlanQuestion): string | null {
  const grounding = question.grounding;
  if (!grounding) return null;
  return [
    `本题来源：候选人简历中的${grounding.kind}「${grounding.label}」。`,
    `原始声明（只供核实，不得擅自扩充事实）：${grounding.evidence}`,
    "判断和追问只能围绕这条声明或候选人本轮新增的自述；不要假定简历未写明的职责、指标或实现。",
  ].join("\n");
}

/**
 * 自由文本追问仍只占一个字段，但在 Harness 侧守住候选人可见契约。
 * 这不是关键词打分：明确的多问号复合题确定性保留第一问；错语言和超长仍拒绝。
 */
export function validateCandidateFollowUp(
  question: string,
  language: "zh-CN" | "en-US" = "zh-CN",
): string {
  const normalized = question.replace(/\s+/g, " ").trim();
  if (normalized.length < 1 || normalized.length > 240) {
    throw new Error(`追问长度必须为 1..240，实际为 ${normalized.length}`);
  }
  const firstQuestionMark = normalized.search(/[？?]/);
  let singleQuestion = normalized;
  if (firstQuestionMark >= 0 && /[？?]/.test(normalized.slice(firstQuestionMark + 1))) {
    singleQuestion = normalized.slice(0, firstQuestionMark + 1);
  }
  const hanCount = [...singleQuestion].filter((char) => char >= "\u3400" && char <= "\u9fff").length;
  const asciiLetters = [...singleQuestion].filter(
    (char) => char.charCodeAt(0) < 128 && /[A-Za-z]/.test(char),
  ).length;
  if (language === "zh-CN" && hanCount < 4) {
    throw new Error("中文面试的候选人可见追问必须使用自然中文句法");
  }
  if (language === "en-US" && asciiLetters < 8) {
    throw new Error("English interviews require candidate-facing follow-ups in English");
  }
  return singleQuestion;
}
