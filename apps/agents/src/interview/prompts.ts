import type { PersonaConfig, PlanQuestion } from "../types.js";
import type { AppliedInterviewDecision, InterviewRuntimeState } from "./contracts.js";
import { candidateQuestionStem, groundingDirective } from "./question-plan.js";

/** F3 自己拥有追问表达策略，不依赖 F4/answer 的 legacy Prompt。 */
const PROBE_STYLE_LADDER: readonly string[] = [
  "L1 直问细节：只追候选人上一答中影响核心判断的实现或因果缺口。",
  "L2 场景检验：施加一个具体条件变化，验证方案边界与取舍。",
  "L3 方向提示：给一个方向性提示，降低难度后只重问一个关键点。",
];

/**
 * mock 面试的稳定 System Prompt。公司、JD、简历等会话变量在首轮上下文注入，
 * 使生产 F3 可以独立演进，也保持跨会话工具/Prompt 前缀稳定。
 */
export function interviewSystemPrompt(): string {
  return [
    "你是大模型应用/Agent 开发岗的资深面试官。你负责理解候选人的回答，并请求下一步控制动作；题号、状态、预算和持久化由 Harness 管理。",
    "",
    "行为规则：",
    "1. 每轮只处理当前问题，一次只追问一个清晰问题；候选人可见追问最多一个问号，不能用‘另外/此外’串联第二问。",
    "2. 回答含糊、只有术语、缺少影响核心判断的因果/实现/边界、明显错误或答非所问时，调用 probe_answer，并把一个自然、具体、可直接展示的问题写入 question。",
    "3. 回答已经回应题意、主要机制正确且基本自洽，或继续追问收益较低时，调用零参数 advance_question。充分不等于完美，不能仅因还能补充更多细节而追问。",
    "4. 每轮必须且只能调用一个控制工具；工具之外不要输出正文。Harness 会发布 probe 的 question，或准确提出题单中的下一题/收尾。",
    "5. 不用字数、关键词数量等表面特征替代语义判断；不暴露参考答案、工具名、导演指令或内部分析。",
    "6. 语气专业克制，不闲聊、不奉承、不羞辱候选人。",
    "7. 候选人可见追问遵守导演指定的面试语言；中文场景用自然中文句法，但保留必要技术术语和代码标识。",
  ].join("\n");
}

/** 所有会话特有信息只在首轮注入，不进入稳定 System Prompt。 */
export function interviewFirstTurnContextDirective(persona: PersonaConfig): string {
  const style = persona.style ?? "礼貌但严格：只围绕影响判断的缺口追问";
  const language = persona.interviewLanguage ?? "zh-CN";
  const parts = [
    "[导演指令·会话上下文] 以下信息只供本场判断与措辞使用，不要念给候选人。",
    `目标岗位：${persona.role}`,
    persona.company ? `目标公司：${persona.company}` : "",
    `面试风格：${style}`,
    `面试语言：${language}。所有候选人可见追问必须使用该语言；技术术语和代码标识可保留原文。`,
    persona.jd ? `目标岗位 JD：\n${persona.jd}` : "",
    persona.brief ? `本场考察简报：${persona.brief}` : "",
    persona.resumeHighlights?.length
      ? `候选人简历要点（不得编造）：\n${persona.resumeHighlights.map((line) => `- ${line}`).join("\n")}`
      : "",
  ];
  return parts.filter(Boolean).join("\n");
}

function questionEvidence(index: number, total: number, question: PlanQuestion): string {
  const answer = question.answer ?? "（没有参考要点，请按专业知识判断）";
  const displayStem = candidateQuestionStem(question);
  const canonical = displayStem !== question.stem ? `\n原始 canonical 题干（只供溯源）：${question.stem}` : "";
  const grounding = groundingDirective(question);
  const probes = question.probes?.length
    ? `\n真实面经追问素材（相关时改写使用）：\n${question.probes.map((probe) => `- ${probe}`).join("\n")}`
    : "";
  return [
    `当前题单第 ${index + 1}/${total} 题（候选人实际看到）：${displayStem}${canonical}`,
    grounding ?? "",
    `参考答案要点（只用于判断，不得直接念给候选人）：${answer}`,
    probes,
  ]
    .filter(Boolean)
    .join("\n");
}

/** 每个回答轮只注入当前 target，永远不提前泄露下一题。 */
export function decisionTurnDirective(
  state: InterviewRuntimeState,
  questions: readonly PlanQuestion[],
): string {
  const probeStyle =
    PROBE_STYLE_LADDER[Math.max(0, Math.min(state.followUpDepth, PROBE_STYLE_LADDER.length - 1))] ??
    PROBE_STYLE_LADDER[0];
  if (state.currentTarget?.kind === "self_intro") {
    return [
      "[导演指令·决策] 候选人正在做自我介绍。判断其中是否有值得立即核实的职责、项目或量化结果。",
      "校准：若已给出明确岗位方向、本人具体贡献，并至少有一个结果或技术取舍，即视为充分并推进；不要为了获得更多细节而追问。只有个人贡献或项目事实无法判断时才追问。",
      `当前追问深度 ${state.followUpDepth}。若追问，表达策略为：${probeStyle}`,
      "只调用 probe_answer 或 advance_question。probe_answer.question 填一个可直接展示的自然追问；advance_question 不填正文。工具之外不要输出文字。",
    ].join("\n");
  }
  if (state.currentTarget?.kind === "plan_question") {
    const question = questions[state.currentTarget.index];
    if (!question) throw new Error(`当前题索引越界: ${state.currentTarget.index}`);
    return [
      "[导演指令·决策] 判断候选人对当前题的回答是否已经覆盖核心并基本自洽。",
      questionEvidence(state.currentTarget.index, questions.length, question),
      "校准：充分不等于完美。回答已解释主要机制/步骤并回应题意时应推进；仅当缺失会妨碍判断的核心因果、实现或边界，或存在明显错误时才追问。不要为了凑追问数量而纠缠。",
      `当前追问深度 ${state.followUpDepth}。若追问，表达策略为：${probeStyle}`,
      "只调用 probe_answer 或 advance_question。probe_answer.question 填一个可直接展示的自然追问；advance_question 不填正文。工具之外不要输出文字。",
    ].join("\n");
  }
  throw new Error(`当前没有可评估 target: ${state.status}/${state.phase}`);
}

export const DECISION_PROTOCOL_CORRECTION = [
  "[协议纠错] 你刚才没有先提交控制动作。",
  "请不要在工具之外输出正文；现在只调用 probe_answer 或 advance_question。若追问，把一个自然、具体且只有一个核心问点的问题填入 probe_answer.question。",
].join("\n");

export function deterministicReply(
  decision: AppliedInterviewDecision | null,
  questions: readonly PlanQuestion[],
  language: PersonaConfig["interviewLanguage"] = "zh-CN",
): string {
  const english = language === "en-US";
  if (!decision) {
    return english
      ? "Let's stay with this question. Please clarify what you personally did and why you made that choice."
      : "我先不切换话题。请再具体说明你刚才提到的做法、你的实际职责，以及这样选择的原因。";
  }
  if (decision.appliedAction === "probe") {
    return (
      decision.followUpQuestion ??
      (english
        ? "Please make that concrete: what did you personally implement, and what was the key trade-off?"
        : "请把刚才的回答再落到实现上：你实际做了什么，关键取舍是什么？")
    );
  }
  const index = decision.introducedQuestionIndex;
  if (index === null || index === undefined) {
    return english
      ? "That concludes today's interview. Thank you for your time."
      : "今天的问题就到这里，感谢你的回答。";
  }
  const question = questions[index] ? candidateQuestionStem(questions[index]) : null;
  if (!question) return english ? "Let's move to the next question." : "我们进入下一题。";
  return english ? `Let's move to the next question: ${question}` : `好，我们进入下一题：${question}`;
}
