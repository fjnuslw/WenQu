import type { AgentTool } from "@earendil-works/pi-agent-core";

import type { AppliedInterviewDecision, RequestedInterviewDecision } from "./contracts.js";

export interface InterviewControlToolOutcome {
  decision: AppliedInterviewDecision;
}

export type InterviewDecisionHandler = (
  request: RequestedInterviewDecision,
) => Promise<InterviewControlToolOutcome>;

interface ProbeArgs {
  question: string;
}

/**
 * F3 的完整模型可见控制面：工具名承载动作，probe 只携带一段自由文本追问。
 * 状态、题号、深度和评分字段一律不进入 schema。
 */
export function buildInterviewControlTools(
  onDecision: InterviewDecisionHandler,
): AgentTool[] {
  const probeAnswer: AgentTool = {
    name: "probe_answer",
    label: "继续追问",
    description:
      "当前回答存在会影响核心判断的关键缺口、明显错误、答非所问或只有术语没有解释时调用。仅仅还能补充更多细节，不构成追问理由。question 填写一个自然、具体、可直接问候选人的追问。",
    parameters: {
      type: "object",
      properties: {
        question: {
          type: "string",
          minLength: 1,
          maxLength: 240,
          description: "候选人可见的单个自然语言追问；不写评分、答案、长分析或思维过程。",
        },
      },
      required: ["question"],
      additionalProperties: false,
    },
    executionMode: "sequential",
    async execute(_toolCallId: string, args: ProbeArgs) {
      const question = args.question.trim();
      if (!question) throw new Error("probe_answer.question 不能为空");
      if (question.length > 240) throw new Error("probe_answer.question 不能超过 240 字符");
      const outcome = await onDecision({ action: "probe", followUpQuestion: question });
      return {
        content: [{ type: "text", text: "追问动作已提交。" }],
        details: outcome.decision,
        terminate: true,
      };
    },
  } as unknown as AgentTool;

  const advanceQuestion: AgentTool = {
    name: "advance_question",
    label: "进入下一题",
    description:
      "当前回答已经充分覆盖问题核心并基本自洽时调用；不要求完美或穷尽所有细节。继续追问收益较低时也应推进。无参数。",
    parameters: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
    executionMode: "sequential",
    async execute() {
      const outcome = await onDecision({ action: "advance" });
      return {
        content: [{ type: "text", text: "推进动作已提交。" }],
        details: outcome.decision,
        terminate: true,
      };
    },
  } as unknown as AgentTool;

  return [probeAnswer, advanceQuestion];
}
