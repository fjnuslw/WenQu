import assert from "node:assert/strict";
import test from "node:test";

import type { PlanQuestion } from "../types.js";
import { decisionEvents, replayInterviewState } from "./events.js";
import { DecisionAlreadyCommitted, InterviewTurnDecisionLatch } from "./orchestrator.js";
import { applyInterviewDecision } from "./policy.js";
import {
  deterministicReply,
  interviewFirstTurnContextDirective,
  interviewSystemPrompt,
} from "./prompts.js";
import {
  candidateQuestionStem,
  groundingDirective,
  validateCandidateFollowUp,
} from "./question-plan.js";
import { initialInterviewState, withNextTurn } from "./state-machine.js";

const questions: PlanQuestion[] = [
  { id: 11, stem: "介绍 RAG 召回链路", kind: "knowledge", answer: "召回、重排、评测" },
  { id: 12, stem: "流量翻倍如何扩容？", kind: "scenario", answer: "瓶颈、降级、容量" },
];

test("F3 稳定 Prompt 不含会话变量，变量只进入首轮上下文", () => {
  const system = interviewSystemPrompt();
  const context = interviewFirstTurnContextDirective({
    company: "合成公司",
    role: "Agent 工程师",
    style: "重视边界条件",
    jd: "负责合成任务",
    brief: "只验证模块边界",
    resumeHighlights: ["实现过合成项目"],
    interviewLanguage: "en-US",
  });

  assert.doesNotMatch(system, /合成公司|Agent 工程师|合成任务|合成项目/);
  assert.match(context, /合成公司/);
  assert.match(context, /Agent 工程师/);
  assert.match(context, /合成任务/);
  assert.match(context, /合成项目/);
  assert.match(context, /面试语言：en-US/);
});

test("候选人只看到本地化题干，简历证据作为受约束的导演上下文", () => {
  const question: PlanQuestion = {
    id: 31,
    stem: "Explain the production RAG pipeline.",
    displayStem: "请结合你做过的系统，说明线上 RAG 链路。",
    kind: "experience",
    answer: null,
    source: "resume",
    grounding: {
      kind: "experience",
      label: "合成科技 · Agent 实习生",
      evidence: "负责知识库召回评测",
    },
  };

  assert.equal(candidateQuestionStem(question), question.displayStem);
  assert.match(groundingDirective(question) ?? "", /负责知识库召回评测/);
  assert.match(groundingDirective(question) ?? "", /不得擅自扩充事实/);
});

test("英文面试的确定性过渡和收尾也不会混入中文", () => {
  const question: PlanQuestion = {
    id: 41,
    stem: "Explain the RAG pipeline.",
    displayStem: "How would you evaluate a production RAG pipeline?",
    kind: "knowledge",
    answer: null,
  };
  const advance = applyInterviewDecision({
    state: withNextTurn(initialInterviewState()),
    request: { action: "advance" },
    questions: [question],
    maxFollowUpDepth: 4,
  });
  const closing = applyInterviewDecision({
    state: withNextTurn(advance.after),
    request: { action: "advance" },
    questions: [question],
    maxFollowUpDepth: 4,
  });

  assert.equal(
    deterministicReply(advance, [question], "en-US"),
    "Let's move to the next question: How would you evaluate a production RAG pipeline?",
  );
  assert.doesNotMatch(deterministicReply(null, [question], "en-US"), /[\u3400-\u9fff]/u);
  assert.doesNotMatch(
    deterministicReply(closing, [question], "en-US"),
    /[\u3400-\u9fff]/u,
  );
});

test("自由文本追问保持单字段，同时由 Harness 拒绝错语言和复合多问", () => {
  assert.equal(
    validateCandidateFollowUp("你如何验证 RAG 的召回质量？", "zh-CN"),
    "你如何验证 RAG 的召回质量？",
  );
  assert.equal(
    validateCandidateFollowUp("你用了哪些指标？另外结果提升了多少？", "zh-CN"),
    "你用了哪些指标？",
  );
  assert.throws(
    () => validateCandidateFollowUp("Explain your evaluation metrics?", "zh-CN"),
    /自然中文句法/,
  );
  assert.throws(
    () => validateCandidateFollowUp("你怎么做的？", "en-US"),
    /in English/,
  );
});

test("初始 target 是自我介绍，advance 后引入第一题", () => {
  const before = withNextTurn(initialInterviewState());
  const result = applyInterviewDecision({
    state: before,
    request: { action: "advance" },
    questions,
    maxFollowUpDepth: 4,
  });

  assert.equal(result.appliedAction, "advance");
  assert.equal(result.introducedQuestionIndex, 0);
  assert.deepEqual(result.after.currentTarget, { kind: "plan_question", index: 0 });
  assert.equal(result.after.phase, "knowledge");
  assert.equal(result.after.followUpDepth, 0);
});

test("probe 保持当前 target 并增加深度", () => {
  const before = withNextTurn(initialInterviewState());
  const result = applyInterviewDecision({
    state: before,
    request: { action: "probe", followUpQuestion: "你在这个项目中具体负责什么？" },
    questions,
    maxFollowUpDepth: 4,
  });

  assert.equal(result.appliedAction, "probe");
  assert.deepEqual(result.after.currentTarget, before.currentTarget);
  assert.equal(result.after.followUpDepth, 1);
  assert.equal(result.followUpQuestion, "你在这个项目中具体负责什么？");
});

test("probe 自由文本仍由领域边界校验，不接收空值或超长内容", () => {
  const state = withNextTurn(initialInterviewState());
  assert.throws(
    () =>
      applyInterviewDecision({
        state,
        request: { action: "probe", followUpQuestion: "   " },
        questions,
        maxFollowUpDepth: 4,
      }),
    /1\.\.240/,
  );
  assert.throws(
    () =>
      applyInterviewDecision({
        state,
        request: { action: "probe", followUpQuestion: "问".repeat(241) },
        questions,
        maxFollowUpDepth: 4,
      }),
    /1\.\.240/,
  );
});

test("达到追问上限后 probe 被 policy 强制转换为 advance", () => {
  const initial = withNextTurn(initialInterviewState());
  const atCap = { ...initial, followUpDepth: 4 };
  const result = applyInterviewDecision({
    state: atCap,
    request: { action: "probe", followUpQuestion: "请继续具体说明。" },
    questions,
    maxFollowUpDepth: 4,
  });

  assert.equal(result.requestedAction, "probe");
  assert.equal(result.appliedAction, "advance");
  assert.equal(result.forcedByPolicy, true);
  assert.equal(result.reasonCode, "followup_cap");
  assert.deepEqual(result.after.currentTarget, { kind: "plan_question", index: 0 });
});

test("题单严格顺序推进，末题后进入 closing", () => {
  let state = withNextTurn(initialInterviewState());
  state = applyInterviewDecision({ state, request: { action: "advance" }, questions, maxFollowUpDepth: 4 }).after;
  state = withNextTurn(state);
  const second = applyInterviewDecision({
    state,
    request: { action: "advance" },
    questions,
    maxFollowUpDepth: 4,
  });
  assert.deepEqual(second.after.currentTarget, { kind: "plan_question", index: 1 });
  assert.equal(second.after.phase, "scenario");
  assert.equal(second.after.questionsInPhase, 1, "跨题型阶段后计数应从 1 重新开始");

  const last = applyInterviewDecision({
    state: withNextTurn(second.after),
    request: { action: "advance" },
    questions,
    maxFollowUpDepth: 4,
  });
  assert.equal(last.introducedQuestionIndex, null);
  assert.equal(last.after.status, "closing");
  assert.equal(last.after.phase, "closing");
  assert.equal(last.after.currentTarget, null);
});

test("单轮 latch 只允许一次状态提交", () => {
  const latch = new InterviewTurnDecisionLatch();
  let commits = 0;
  const apply = () => {
    commits += 1;
    return applyInterviewDecision({
      state: withNextTurn(initialInterviewState()),
      request: { action: "probe" as const, followUpQuestion: "请具体说明。" },
      questions,
      maxFollowUpDepth: 4,
    });
  };

  latch.commit(apply);
  assert.throws(() => latch.commit(apply), DecisionAlreadyCommitted);
  assert.equal(commits, 1);
});

test("state_transition 事件可以重放得到相同状态", () => {
  const initial = initialInterviewState();
  const before = withNextTurn(initial);
  const decision = applyInterviewDecision({
    state: before,
    request: { action: "advance" },
    questions,
    maxFollowUpDepth: 4,
  });
  const events = decisionEvents(decision, questions);

  assert.deepEqual(replayInterviewState(initial, events), decision.after);
  assert.equal(events[0].questionId, null);
  assert.equal(events[0].turnNo, 1);
});
