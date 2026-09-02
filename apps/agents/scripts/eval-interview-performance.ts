import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import type { Agent } from "@earendil-works/pi-agent-core";

import { loadConfig, type AgentServiceConfig } from "../src/config.js";
import { buildInterviewControlTools } from "../src/interview/control-tools.js";
import type { AppliedInterviewDecision } from "../src/interview/contracts.js";
import { f3ImplementationSha256 } from "../src/interview/eval-signature.js";
import { applyInterviewDecision } from "../src/interview/policy.js";
import {
  DECISION_PROTOCOL_CORRECTION,
  decisionTurnDirective,
  interviewSystemPrompt,
} from "../src/interview/prompts.js";
import { initialInterviewState, phaseForQuestionKind, withNextTurn } from "../src/interview/state-machine.js";
import { bootstrapPi } from "../src/pi.js";
import { systemPrompt } from "../src/prompts.js";
import type { PlanQuestion, SessionConfig } from "../src/types.js";

interface DecisionFixture {
  id: string;
  kind: string;
  question: string;
  referencePoints: string[];
  candidateAnswer: string;
}

interface PairResult {
  id: string;
  order: "legacy-first" | "v2-first";
  legacyLatencyMs: number;
  v2LatencyMs: number;
  v2Decision: "probe" | "advance" | null;
  v2Retried: boolean;
}

function numberArg(name: string, fallback: number): number {
  const index = process.argv.indexOf(name);
  if (index === -1) return fallback;
  const value = Number(process.argv[index + 1]);
  if (!Number.isInteger(value) || value < 1) throw new Error(`${name} 必须是正整数`);
  return value;
}

function stringArg(name: string): string | null {
  const index = process.argv.indexOf(name);
  return index === -1 ? null : (process.argv[index + 1] ?? null);
}

function thinkingArg(config: AgentServiceConfig): AgentServiceConfig["thinkingLevel"] {
  const value = stringArg("--thinking") ?? "medium";
  const allowed: AgentServiceConfig["thinkingLevel"][] = ["minimal", "low", "medium", "high", "xhigh", "max"];
  const match = allowed.find((candidate) => candidate === value);
  if (!match) throw new Error(`--thinking 非法: ${value}`);
  return match ?? config.thinkingLevel;
}

function percentile(values: readonly number[], ratio: number): number {
  const ordered = [...values].sort((a, b) => a - b);
  const index = Math.max(0, Math.min(ordered.length - 1, Math.ceil(ordered.length * ratio) - 1));
  return ordered[index] ?? 0;
}

/** 去掉 v2 新增的工具约束，近似改造前“一次模型生成正文”的生产路径。 */
function legacySystemPrompt(config: SessionConfig): string {
  return systemPrompt(config)
    .split("\n")
    .filter((line) => !/^(7|8|9|10)\. /.test(line))
    .join("\n");
}

function fixtureContext(fixture: DecisionFixture) {
  const question: PlanQuestion = {
    id: 1,
    stem: fixture.question,
    kind: fixture.kind === "self_intro" ? "knowledge" : fixture.kind,
    answer: fixture.referencePoints.join("；"),
  };
  const state = withNextTurn(initialInterviewState());
  const questions =
    fixture.kind === "self_intro"
      ? [question]
      : [
          question,
          {
            id: 2,
            stem: "请结合另一个实际案例说明你的取舍。",
            kind: "scenario",
            answer: "背景、约束、方案、结果",
          },
        ];
  if (fixture.kind !== "self_intro") {
    state.phase = phaseForQuestionKind(fixture.kind);
    state.currentTarget = { kind: "plan_question", index: 0 };
  }
  const config: SessionConfig = {
    mode: "mock",
    persona: { role: "大模型应用开发候选人" },
    maxQuestionsPerPhase: 4,
    maxFollowUpDepth: 4,
    questions,
  };
  return { question, questions, state, config };
}

async function measureLegacy(
  fixture: DecisionFixture,
  runtime: ReturnType<typeof bootstrapPi>,
  thinkingLevel: AgentServiceConfig["thinkingLevel"],
): Promise<number> {
  const { question, config } = fixtureContext(fixture);
  const agent: Agent = runtime.agentFactory(legacySystemPrompt(config), undefined, thinkingLevel);
  const prompt = [
    "[导演指令] 根据当前题与候选人回答，直接生成一句自然的面试官追问或过渡；每轮只问一个问题。",
    `当前题：${fixture.kind === "self_intro" ? "候选人自我介绍" : question.stem}`,
    `参考要点：${question.answer}`,
    `候选人发言：${fixture.candidateAnswer}`,
  ].join("\n");
  const started = performance.now();
  await agent.prompt(prompt);
  return Math.round(performance.now() - started);
}

async function measureV2(
  fixture: DecisionFixture,
  runtime: ReturnType<typeof bootstrapPi>,
  thinkingLevel: AgentServiceConfig["thinkingLevel"],
): Promise<{ latencyMs: number; decision: PairResult["v2Decision"]; retried: boolean }> {
  const { questions, state, config } = fixtureContext(fixture);
  let decision: AppliedInterviewDecision | null = null;
  const tools = buildInterviewControlTools(async (request) => {
    if (decision) throw new Error("性能评测轮出现重复动作");
    decision = applyInterviewDecision({
      state,
      request,
      questions,
      maxFollowUpDepth: 4,
    });
    const committed = decision as AppliedInterviewDecision;
    return {
      decision: committed,
    };
  });
  const agent: Agent = runtime.agentFactory(interviewSystemPrompt(), tools, thinkingLevel);
  const prompt = `${decisionTurnDirective(state, questions)}\n\n候选人发言：${fixture.candidateAnswer}`;
  const started = performance.now();
  let retried = false;
  await agent.prompt(prompt);
  if (!decision) {
    retried = true;
    await agent.prompt(DECISION_PROTOCOL_CORRECTION);
  }
  return {
    latencyMs: Math.round(performance.now() - started),
    decision: decision ? (decision as AppliedInterviewDecision).appliedAction : null,
    retried,
  };
}

async function main() {
  const config = loadConfig();
  if (!config.hasApiKey) throw new Error("DEEPSEEK_API_KEY 未配置，无法运行性能 A/B");
  const fixturesPath = path.resolve(process.cwd(), "evals/f3-decision-fixtures.json");
  const fixtureRaw = await readFile(fixturesPath, "utf8");
  const fixtures = (JSON.parse(fixtureRaw) as DecisionFixture[]).slice(0, numberArg("--limit", 10));
  const thinkingLevel = thinkingArg(config);
  const runtime = bootstrapPi(config);
  const results: PairResult[] = [];

  for (const [index, fixture] of fixtures.entries()) {
    let legacyLatencyMs: number;
    let v2: Awaited<ReturnType<typeof measureV2>>;
    if (index % 2 === 0) {
      legacyLatencyMs = await measureLegacy(fixture, runtime, thinkingLevel);
      v2 = await measureV2(fixture, runtime, thinkingLevel);
    } else {
      v2 = await measureV2(fixture, runtime, thinkingLevel);
      legacyLatencyMs = await measureLegacy(fixture, runtime, thinkingLevel);
    }
    results.push({
      id: fixture.id,
      order: index % 2 === 0 ? "legacy-first" : "v2-first",
      legacyLatencyMs,
      v2LatencyMs: v2.latencyMs,
      v2Decision: v2.decision,
      v2Retried: v2.retried,
    });
    console.log(
      `[${index + 1}/${fixtures.length}] ${fixture.id} legacy=${legacyLatencyMs}ms v2=${v2.latencyMs}ms`,
    );
  }

  const legacy = results.map((item) => item.legacyLatencyMs);
  const v2 = results.map((item) => item.v2LatencyMs);
  const legacyP50 = percentile(legacy, 0.5);
  const metrics = {
    pairCount: results.length,
    decisionCoverage: results.filter((item) => item.v2Decision !== null).length / results.length,
    retryRate: results.filter((item) => item.v2Retried).length / results.length,
    legacyP50LatencyMs: legacyP50,
    legacyP95LatencyMs: percentile(legacy, 0.95),
    v2P50LatencyMs: percentile(v2, 0.5),
    v2P95LatencyMs: percentile(v2, 0.95),
    p50Ratio: legacyP50 ? percentile(v2, 0.5) / legacyP50 : null,
  };
  const passed =
    metrics.decisionCoverage === 1 &&
    metrics.retryRate === 0 &&
    metrics.p50Ratio !== null &&
    metrics.p50Ratio <= 2.2;
  const artifact = {
    createdAt: new Date().toISOString(),
    model: config.defaultModel,
    thinkingLevel,
    protocolVariant: "one_step_question_arg",
    implementationSha256: await f3ImplementationSha256(),
    fixtureSha256: createHash("sha256").update(fixtureRaw).digest("hex"),
    fixtureIds: fixtures.map((item) => item.id),
    metrics,
    passed,
    results,
  };
  const outputDir = path.resolve(process.cwd(), "../../data/evals");
  await mkdir(outputDir, { recursive: true });
  const output = stringArg("--output")
    ? path.resolve(process.cwd(), stringArg("--output") as string)
    : path.join(outputDir, `f3-performance-${new Date().toISOString().replaceAll(":", "-")}.json`);
  await writeFile(output, `${JSON.stringify(artifact, null, 2)}\n`, "utf8");
  console.log(JSON.stringify({ metrics, passed }, null, 2));
  console.log(`result=${output}`);
  if (!passed) process.exitCode = 1;
}

await main();
