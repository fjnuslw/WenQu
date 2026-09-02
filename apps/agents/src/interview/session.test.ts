import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import type { Agent, AgentTool } from "@earendil-works/pi-agent-core";

import type { AgentServiceConfig } from "../config.js";
import type { PiRuntime } from "../pi.js";
import { SessionManager } from "../session.js";
import type { ClientEvent, PlanQuestion, SessionConfig } from "../types.js";

type FakeAction = "probe" | "advance" | "missing" | "error";

interface FakeScriptStep {
  action: FakeAction;
  preDecisionText?: string;
  finalText?: string;
  followUpQuestion?: string;
  thinkingText?: string;
  pause?: Promise<void>;
  repeatAction?: boolean;
}

class FakeAgent {
  readonly state = { messages: [] as unknown[] };
  private readonly listeners: Array<(event: unknown, signal: AbortSignal) => Promise<void> | void> = [];
  private promptNo = 0;

  constructor(
    private readonly tools: AgentTool[],
    private readonly script: FakeScriptStep[],
  ) {}

  subscribe(listener: (event: unknown, signal: AbortSignal) => Promise<void> | void): () => void {
    this.listeners.push(listener);
    return () => undefined;
  }

  async prompt(): Promise<void> {
    const step = this.script[this.promptNo] ?? this.script[this.script.length - 1];
    this.promptNo += 1;
    if (!step) throw new Error("FakeAgent 没有脚本步骤");
    if (step.pause) await step.pause;
    if (step.thinkingText) await this.thinking(step.thinkingText);
    if (step.preDecisionText) await this.text(step.preDecisionText);
    if (step.action === "error") throw new Error("synthetic model failure");
    if (step.action === "missing") return;

    const toolName = step.action === "probe" ? "probe_answer" : "advance_question";
    const tool = this.tools.find((candidate) => candidate.name === toolName);
    if (!tool) throw new Error(`FakeAgent 缺少工具: ${toolName}`);
    const args =
      step.action === "probe"
        ? { question: step.followUpQuestion ?? "请把关键实现和取舍再具体说明一下？" }
        : {};
    const execute = async (suffix: string) => {
      const toolCallId = `call-${this.promptNo}-${suffix}`;
      await this.emit({ type: "tool_execution_start", toolCallId, toolName, args });
      const result = await tool.execute(toolCallId, args, undefined, undefined);
      await this.emit({ type: "tool_execution_end", toolCallId, toolName, result, isError: false });
      return result;
    };
    const result = await execute("first");
    if (step.repeatAction) {
      await assert.rejects(execute("duplicate"), /已经提交/);
    }
    if (step.finalText && !(result as { terminate?: boolean }).terminate) await this.text(step.finalText);
  }

  private async text(delta: string): Promise<void> {
    await this.emit({
      type: "message_update",
      message: { role: "assistant", content: [{ type: "text", text: delta }] },
      assistantMessageEvent: { type: "text_delta", delta },
    });
  }

  private async thinking(delta: string): Promise<void> {
    await this.emit({
      type: "message_update",
      assistantMessageEvent: { type: "thinking_delta", delta },
    });
  }

  private async emit(event: unknown): Promise<void> {
    const signal = new AbortController().signal;
    for (const listener of this.listeners) await listener(event, signal);
  }
}

const questions: PlanQuestion[] = [
  { id: 101, stem: "请说明 RAG 的完整链路。", kind: "knowledge", answer: "召回、重排、生成、评测" },
  { id: 102, stem: "高并发下如何降级？", kind: "scenario", answer: "限流、缓存、熔断" },
];

function sessionConfig(): SessionConfig {
  return {
    mode: "mock",
    persona: { role: "大模型应用开发" },
    maxQuestionsPerPhase: 4,
    maxFollowUpDepth: 4,
    questions,
  };
}

async function fixture(script: FakeScriptStep[], requestedConfig: SessionConfig = sessionConfig()) {
  const dataDir = await mkdtemp(path.join(tmpdir(), "wenqu-agent-test-"));
  const config: AgentServiceConfig = {
    port: 0,
    dataDir,
    apiBaseUrl: "http://127.0.0.1:0",
    defaultModel: "fake",
    thinkingLevel: "medium",
    hasApiKey: true,
  };
  const runtime: PiRuntime = {
    agentFactory: (_systemPrompt, tools = []) => new FakeAgent(tools, script) as unknown as Agent,
  };
  const manager = new SessionManager(runtime, config);
  const id = await manager.create(requestedConfig);
  return {
    id,
    manager,
    dataDir,
    async log() {
      return await readFile(path.join(dataDir, `${id}.jsonl`), "utf8");
    },
    async cleanup() {
      await rm(dataDir, { recursive: true, force: true });
    },
  };
}

test("F3 v2 只接收模型工具动作，advance 后由 Harness 引入第一题", async () => {
  const fx = await fixture([{ action: "advance", finalText: "我们进入第一题：请说明 RAG 的完整链路。" }]);
  try {
    const events: ClientEvent[] = [];
    const outcome = await fx.manager.turn(fx.id, { text: "我做过一个知识库项目。" }, (event) => events.push(event));

    assert.equal(outcome.reply, "好，我们进入下一题：请说明 RAG 的完整链路。");
    assert.equal(outcome.phase, "knowledge");
    assert.equal(outcome.followUpDepth, 0);
    assert.ok(
      events.some(
        (event) => event.type === "decision" && event.action === "advance" && event.followUpDepth === 0,
      ),
    );
    assert.ok(events.some((event) => event.type === "question" && event.index === 1));
    assert.match(await fx.log(), /"type":"interview_decision"/);
    assert.match(await fx.log(), /"requestedAction":"advance"/);
  } finally {
    await fx.cleanup();
  }
});

test("简历经历题使用中文展示层、项目阶段和可追溯 SSE 元数据", async () => {
  const resumeQuestion: PlanQuestion = {
    id: -1,
    stem: "[resume:experience] canonical evidence question",
    displayStem: "你在合成科技实习时具体负责哪部分，关键决策是什么？",
    kind: "experience",
    answer: null,
    source: "resume",
    grounding: {
      kind: "experience",
      label: "合成科技 · Agent 实习生",
      evidence: "负责 RAG 评测链路",
    },
  };
  const requestedConfig: SessionConfig = {
    ...sessionConfig(),
    persona: { role: "大模型应用开发", interviewLanguage: "zh-CN" },
    questions: [resumeQuestion],
  };
  const fx = await fixture(
    [
      { action: "advance" },
      { action: "probe", followUpQuestion: "你如何证明这套评测结论可信？" },
    ],
    requestedConfig,
  );
  try {
    const events: ClientEvent[] = [];
    const outcome = await fx.manager.turn(fx.id, { text: "我主要做 Agent 工程。" }, (event) =>
      events.push(event),
    );

    assert.equal(outcome.reply, `好，我们进入下一题：${resumeQuestion.displayStem}`);
    assert.equal(outcome.phase, "project");
    assert.ok(
      events.some(
        (event) =>
          event.type === "question" &&
          event.stem === resumeQuestion.displayStem &&
          event.source === "resume" &&
          event.groundingLabel === "合成科技 · Agent 实习生",
      ),
    );
    await fx.manager.turn(fx.id, { text: "我负责设计离线评测。" }, () => undefined);
    const log = await fx.log();
    assert.match(log, /负责 RAG 评测链路/);
    assert.match(log, /不得擅自扩充事实/);
  } finally {
    await fx.cleanup();
  }
});

test("输出闸门丢弃工具外正文，只发布 probe 参数中的自由文本追问", async () => {
  const fx = await fixture([
    {
      action: "probe",
      thinkingText: "这段隐藏推理不能进入 F3 SSE 或日志。",
      preDecisionText: "这段不应该让候选人看到。",
      followUpQuestion: "你在这个项目中具体负责哪一段链路？",
    },
  ]);
  try {
    const events: ClientEvent[] = [];
    const outcome = await fx.manager.turn(fx.id, { text: "我们团队做了很多优化。" }, (event) => events.push(event));
    const visible = events
      .filter((event): event is Extract<ClientEvent, { type: "text_delta" }> => event.type === "text_delta")
      .map((event) => event.delta)
      .join("");

    assert.equal(outcome.reply, "你在这个项目中具体负责哪一段链路？");
    assert.equal(outcome.thinking, "");
    assert.equal(visible, outcome.reply);
    assert.ok(!visible.includes("不应该"));
    assert.equal(outcome.followUpDepth, 1);
    assert.ok(
      events.some(
        (event) => event.type === "decision" && event.action === "probe" && event.followUpDepth === 1,
      ),
    );
    assert.match(await fx.log(), /"code":"output_before_decision"/);
    assert.doesNotMatch(await fx.log(), /隐藏推理/);
    assert.ok(!events.some((event) => event.type === "thinking_delta"));
  } finally {
    await fx.cleanup();
  }
});

test("复合追问只发布第一问并留下可审计协议事件", async () => {
  const fx = await fixture([
    {
      action: "probe",
      followUpQuestion: "你具体负责哪一段链路？另外结果提升了多少？",
    },
  ]);
  try {
    const outcome = await fx.manager.turn(fx.id, { text: "我们做了不少优化。" }, () => undefined);

    assert.equal(outcome.reply, "你具体负责哪一段链路？");
    const log = await fx.log();
    assert.match(log, /"code":"invalid_decision"/);
    assert.match(log, /Harness 只保留第一问/);
  } finally {
    await fx.cleanup();
  }
});

test("缺失控制工具时只重试一次；再次失败后保持状态并安全追问", async () => {
  const fx = await fixture([
    { action: "missing", preDecisionText: "直接换下一题。" },
    { action: "missing", preDecisionText: "还是没有调用工具。" },
  ]);
  try {
    const events: ClientEvent[] = [];
    const before = fx.manager.snapshot(fx.id);
    const outcome = await fx.manager.turn(fx.id, { text: "不知道。" }, (event) => events.push(event));
    const after = fx.manager.snapshot(fx.id);

    assert.equal(after.phase, before.phase);
    assert.equal(after.followUpDepth, before.followUpDepth);
    assert.equal(after.turnNo, before.turnNo);
    assert.match(outcome.reply, /不切换话题/);
    assert.ok(!outcome.reply.includes("直接换下一题"));
    const log = await fx.log();
    assert.equal((log.match(/"code":"missing_decision"/g) ?? []).length, 2);
    assert.doesNotMatch(log, /"type":"interview_decision"/);
  } finally {
    await fx.cleanup();
  }
});

test("mock 无题单被领域入口显式拒绝，不回落到 legacy 自动推进", async () => {
  const dataDir = await mkdtemp(path.join(tmpdir(), "wenqu-agent-test-"));
  const config: AgentServiceConfig = {
    port: 0,
    dataDir,
    apiBaseUrl: "http://127.0.0.1:0",
    defaultModel: "fake",
    thinkingLevel: "medium",
    hasApiKey: true,
  };
  const runtime: PiRuntime = {
    agentFactory: () => {
      throw new Error("无题单校验应发生在 agent 创建之前");
    },
  };
  const manager = new SessionManager(runtime, config);
  try {
    await assert.rejects(
      manager.create({
        mode: "mock",
        persona: { role: "大模型应用开发" },
        maxQuestionsPerPhase: 4,
        maxFollowUpDepth: 4,
      }),
      /必须提供非空题单/,
    );
  } finally {
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("同一模型轮重复调用控制工具只提交一次并留下协议事件", async () => {
  const fx = await fixture([
    {
      action: "advance",
      repeatAction: true,
      finalText: "我们进入第一题：请说明 RAG 的完整链路。",
    },
  ]);
  try {
    const events: ClientEvent[] = [];
    await fx.manager.turn(fx.id, { text: "我负责知识库检索链路。" }, (event) => events.push(event));

    const log = await fx.log();
    assert.equal((log.match(/"type":"interview_decision"/g) ?? []).length, 1);
    assert.equal((log.match(/"type":"state_transition"/g) ?? []).length, 1);
    assert.equal((log.match(/"code":"duplicate_decision"/g) ?? []).length, 1);
    assert.equal(events.filter((event) => event.type === "decision").length, 1);
    assert.deepEqual(fx.manager.snapshot(fx.id).currentTarget, { kind: "plan_question", index: 0 });
  } finally {
    await fx.cleanup();
  }
});

test("单会话并发 turn 被拒绝，不会覆盖在飞轮次的 latch", async () => {
  let release!: () => void;
  const pause = new Promise<void>((resolve) => {
    release = resolve;
  });
  const fx = await fixture([
    {
      action: "advance",
      pause,
      finalText: "我们进入第一题：请说明 RAG 的完整链路。",
    },
  ]);
  try {
    const first = fx.manager.turn(fx.id, { text: "第一条候选人回答" }, () => undefined);
    await new Promise<void>((resolve) => setImmediate(resolve));
    await assert.rejects(
      fx.manager.turn(fx.id, { text: "并发重复回答" }, () => undefined),
      /已有一轮正在处理/,
    );
    release();
    await first;

    const log = await fx.log();
    assert.equal((log.match(/"type":"user"/g) ?? []).length, 1);
    assert.equal((log.match(/"type":"interview_decision"/g) ?? []).length, 1);
  } finally {
    release();
    await fx.cleanup();
  }
});

test("F4 与 answer 继续走独立 legacy I/O 壳，不依赖 F3 控制工具", async () => {
  const configs: SessionConfig[] = [
    {
      mode: "answer",
      persona: { role: "大模型应用开发" },
      maxQuestionsPerPhase: 4,
      maxFollowUpDepth: 4,
    },
    {
      mode: "grill",
      persona: { role: "项目拷打候选人" },
      maxQuestionsPerPhase: 4,
      maxFollowUpDepth: 4,
      grill: {
        projectId: 1,
        projectName: "synthetic-project",
        repoRoot: ".",
        briefing: { overview: "测试项目", stack_summary: "TypeScript", modules: [] },
      },
    },
  ];

  for (const requestedConfig of configs) {
    const reply = `${requestedConfig.mode} 模式回复`;
    const thinking = `${requestedConfig.mode} 模式思考`;
    const fx = await fixture([{ action: "missing", thinkingText: thinking, preDecisionText: reply }], requestedConfig);
    try {
      const outcome = await fx.manager.turn(fx.id, { text: "请继续" }, () => undefined);
      assert.equal(outcome.reply, reply);
      assert.equal(outcome.thinking, thinking);
      assert.doesNotMatch(await fx.log(), /"type":"interview_decision"/);
    } finally {
      await fx.cleanup();
    }
  }
});

test("模型在决策前失败时回滚临时 turn 状态", async () => {
  const fx = await fixture([{ action: "error", preDecisionText: "不可见半句" }]);
  try {
    const before = fx.manager.snapshot(fx.id);
    await assert.rejects(
      fx.manager.turn(fx.id, { text: "候选人回答" }, () => undefined),
      /synthetic model failure/,
    );
    const after = fx.manager.snapshot(fx.id);
    assert.deepEqual(after, before);
    const log = await fx.log();
    assert.match(log, /"code":"model_error"/);
    assert.doesNotMatch(log, /"type":"state_transition"/);
  } finally {
    await fx.cleanup();
  }
});

test("进入 closing 后拒绝新回答，decision 覆盖口径不被结束后输入污染", async () => {
  const fx = await fixture([
    { action: "advance", finalText: "第一题。" },
    { action: "advance", finalText: "第二题。" },
    { action: "advance", finalText: "面试结束。" },
  ]);
  try {
    for (let index = 0; index < 3; index += 1) {
      await fx.manager.turn(fx.id, { text: `回答 ${index + 1}` }, () => undefined);
    }
    assert.equal(fx.manager.snapshot(fx.id).status, "closing");
    await assert.rejects(
      fx.manager.turn(fx.id, { text: "结束后多发的一条" }, () => undefined),
      /已经进入收尾/,
    );
    const log = await fx.log();
    assert.equal((log.match(/"type":"user"/g) ?? []).length, 3);
    assert.equal((log.match(/"type":"interview_decision"/g) ?? []).length, 3);
  } finally {
    await fx.cleanup();
  }
});
