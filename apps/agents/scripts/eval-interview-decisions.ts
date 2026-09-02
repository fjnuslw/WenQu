import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import type { Agent } from "@earendil-works/pi-agent-core";

import { loadConfig, type AgentServiceConfig } from "../src/config.js";
import { buildInterviewControlTools } from "../src/interview/control-tools.js";
import type { AppliedInterviewDecision, InterviewDecisionAction } from "../src/interview/contracts.js";
import { f3ImplementationSha256 } from "../src/interview/eval-signature.js";
import { applyInterviewDecision } from "../src/interview/policy.js";
import {
  DECISION_PROTOCOL_CORRECTION,
  decisionTurnDirective,
  interviewSystemPrompt,
} from "../src/interview/prompts.js";
import {
  initialInterviewState,
  phaseForQuestionKind,
  withNextTurn,
} from "../src/interview/state-machine.js";
import { bootstrapPi } from "../src/pi.js";
import type { PlanQuestion } from "../src/types.js";

interface DecisionFixture {
  id: string;
  category: string;
  kind: string;
  question: string;
  referencePoints: string[];
  candidateAnswer: string;
  expectedAction: InterviewDecisionAction;
  goldRationale: string;
}

interface EvalResult {
  id: string;
  category: string;
  expected: InterviewDecisionAction;
  predicted: InterviewDecisionAction | null;
  correct: boolean;
  retried: boolean;
  latencyMs: number;
  error?: string;
}

function numberArg(name: string, fallback: number): number {
  const index = process.argv.indexOf(name);
  if (index === -1) return fallback;
  const value = Number(process.argv[index + 1]);
  if (!Number.isInteger(value) || value < 0) throw new Error(`${name} 必须是非负整数`);
  return value;
}

function stringArg(name: string): string | null {
  const index = process.argv.indexOf(name);
  if (index === -1) return null;
  return process.argv[index + 1] ?? null;
}

function thinkingArg(config: AgentServiceConfig): AgentServiceConfig["thinkingLevel"] {
  const value = stringArg("--thinking") ?? "medium";
  const allowed: AgentServiceConfig["thinkingLevel"][] = ["minimal", "low", "medium", "high", "xhigh", "max"];
  const match = allowed.find((candidate) => candidate === value);
  if (!match) throw new Error(`--thinking 非法: ${value}`);
  return match ?? config.thinkingLevel;
}

function fixtureState(fixture: DecisionFixture) {
  const base = withNextTurn(initialInterviewState());
  if (fixture.kind === "self_intro") return base;
  return {
    ...base,
    phase: phaseForQuestionKind(fixture.kind),
    currentTarget: { kind: "plan_question" as const, index: 0 },
  };
}

async function evaluateOne(
  fixture: DecisionFixture,
  runtime: ReturnType<typeof bootstrapPi>,
  thinkingLevel: AgentServiceConfig["thinkingLevel"],
): Promise<EvalResult> {
  const question: PlanQuestion = {
    id: 1,
    stem: fixture.question,
    kind: fixture.kind === "self_intro" ? "knowledge" : fixture.kind,
    answer: fixture.referencePoints.join("；"),
  };
  const questions = [question];
  const state = fixtureState(fixture);
  const capture: { decision: AppliedInterviewDecision | null } = { decision: null };
  const tools = buildInterviewControlTools(async (request) => {
    if (capture.decision) throw new Error("评测轮次出现重复控制动作");
    capture.decision = applyInterviewDecision({
      state,
      request,
      questions,
      maxFollowUpDepth: 4,
    });
    return { decision: capture.decision };
  });
  const agent: Agent = runtime.agentFactory(
    interviewSystemPrompt(),
    tools,
    thinkingLevel,
    `f3-eval-${fixture.id}`,
  );
  const prompt = `${decisionTurnDirective(state, questions)}\n\n候选人发言：${fixture.candidateAnswer}`;
  const started = performance.now();
  let retried = false;
  let error: string | undefined;
  try {
    await agent.prompt(prompt);
    if (!capture.decision) {
      retried = true;
      await agent.prompt(DECISION_PROTOCOL_CORRECTION);
    }
    if (!capture.decision && agent.state.errorMessage) error = agent.state.errorMessage;
  } catch (caught) {
    error = caught instanceof Error ? caught.message : String(caught);
  }
  const predicted = capture.decision?.appliedAction ?? null;
  return {
    id: fixture.id,
    category: fixture.category,
    expected: fixture.expectedAction,
    predicted,
    correct: predicted === fixture.expectedAction,
    retried,
    latencyMs: Math.round(performance.now() - started),
    ...(error ? { error } : {}),
  };
}

function summarize(results: EvalResult[]) {
  const total = results.length;
  const correct = results.filter((item) => item.correct).length;
  const probeGold = results.filter((item) => item.expected === "probe");
  const advanceGold = results.filter((item) => item.expected === "advance");
  const captured = results.filter((item) => item.predicted !== null).length;
  const probeTruePositive = probeGold.filter((item) => item.predicted === "probe").length;
  const falseProbe = advanceGold.filter((item) => item.predicted === "probe").length;
  const sortedLatency = results.map((item) => item.latencyMs).sort((a, b) => a - b);
  const percentile = (ratio: number) => sortedLatency[Math.min(sortedLatency.length - 1, Math.floor(total * ratio))] ?? 0;
  const metrics = {
    total,
    correct,
    accuracy: total ? correct / total : 0,
    decisionCoverage: total ? captured / total : 0,
    probeRecall: probeGold.length ? probeTruePositive / probeGold.length : 0,
    falseProbeRate: advanceGold.length ? falseProbe / advanceGold.length : 0,
    retryRate: total ? results.filter((item) => item.retried).length / total : 0,
    p50LatencyMs: percentile(0.5),
    p95LatencyMs: percentile(0.95),
  };
  const passed =
    metrics.accuracy >= 0.85 &&
    metrics.decisionCoverage === 1 &&
    metrics.probeRecall >= 0.85 &&
    metrics.falseProbeRate <= 0.15;
  return { metrics, passed };
}

async function main() {
  const config = loadConfig();
  if (!config.hasApiKey) throw new Error("DEEPSEEK_API_KEY 未配置，无法运行真实模型 decision eval");
  const fixturesPath = path.resolve(process.cwd(), "evals/f3-decision-fixtures.json");
  const fixtureRaw = await readFile(fixturesPath, "utf8");
  const fixtures = JSON.parse(fixtureRaw) as DecisionFixture[];
  const offset = numberArg("--offset", 0);
  const requestedLimit = numberArg("--limit", fixtures.length);
  const selected = fixtures.slice(offset, offset + requestedLimit);
  if (!selected.length) throw new Error("评测样本为空");

  const thinkingLevel = thinkingArg(config);
  const runtime = bootstrapPi(config);
  const results: EvalResult[] = [];
  for (const [index, fixture] of selected.entries()) {
    const result = await evaluateOne(fixture, runtime, thinkingLevel);
    results.push(result);
    const mark = result.correct ? "PASS" : "FAIL";
    console.log(
      `[${index + 1}/${selected.length}] ${mark} ${fixture.id}: expected=${result.expected} predicted=${result.predicted ?? "none"} ${result.latencyMs}ms`,
    );
  }

  const summary = summarize(results);
  const artifact = {
    createdAt: new Date().toISOString(),
    model: config.defaultModel,
    thinkingLevel,
    protocolVariant: "one_step_question_arg",
    implementationSha256: await f3ImplementationSha256(),
    fixtureSha256: createHash("sha256").update(fixtureRaw).digest("hex"),
    fixtureOffset: offset,
    fixtureCount: selected.length,
    ...summary,
    results,
  };
  const explicitOutput = stringArg("--output");
  const outputDir = path.resolve(process.cwd(), "../../data/evals");
  await mkdir(outputDir, { recursive: true });
  const output = explicitOutput
    ? path.resolve(process.cwd(), explicitOutput)
    : path.join(outputDir, `f3-decision-${new Date().toISOString().replaceAll(":", "-")}.json`);
  await writeFile(output, `${JSON.stringify(artifact, null, 2)}\n`, "utf8");

  console.log(JSON.stringify(summary, null, 2));
  console.log(`result=${output}`);
  if (!summary.passed) process.exitCode = 1;
}

await main();
