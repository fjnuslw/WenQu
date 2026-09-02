import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import {
  F3_IMPLEMENTATION_SCOPE_VERSION,
  f3ImplementationSha256,
} from "./eval-signature.js";

interface DecisionFixture {
  id: string;
  category: string;
  kind: string;
  question: string;
  referencePoints: string[];
  candidateAnswer: string;
  expectedAction: "probe" | "advance";
  goldRationale: string;
}

async function loadFixtures(): Promise<DecisionFixture[]> {
  const file = path.resolve(process.cwd(), "evals/f3-decision-fixtures.json");
  return JSON.parse(await readFile(file, "utf8")) as DecisionFixture[];
}

test("F3 decision 金标准不少于 50 条且标签平衡", async () => {
  const fixtures = await loadFixtures();
  assert.ok(fixtures.length >= 50);
  assert.equal(new Set(fixtures.map((item) => item.id)).size, fixtures.length);
  assert.ok(new Set(fixtures.map((item) => item.category)).size >= 5);

  const probe = fixtures.filter((item) => item.expectedAction === "probe").length;
  const advance = fixtures.filter((item) => item.expectedAction === "advance").length;
  assert.ok(probe >= 20, `probe 样本不足: ${probe}`);
  assert.ok(advance >= 20, `advance 样本不足: ${advance}`);
  for (const item of fixtures) {
    assert.ok(item.question.trim().length >= 6, `${item.id} 缺少题目`);
    assert.ok(item.candidateAnswer.trim().length >= 4, `${item.id} 缺少候选人回答`);
    assert.ok(item.referencePoints.length >= 2, `${item.id} 参考点不足`);
    assert.ok(item.goldRationale.trim().length >= 6, `${item.id} 缺少人工理由`);
  }
});

test("金标准包含 Prompt injection 与自我介绍边界样本", async () => {
  const fixtures = await loadFixtures();
  assert.ok(fixtures.some((item) => item.kind === "self_intro"));
  assert.ok(fixtures.some((item) => item.candidateAnswer.includes("忽略面试规则")));
  assert.ok(fixtures.some((item) => item.candidateAnswer.includes("SYSTEM:")));
});

test("提交的实模基线绑定当前 fixture，且决策与追问相关性均过门槛", async () => {
  const fixtureRaw = await readFile(path.resolve(process.cwd(), "evals/f3-decision-fixtures.json"), "utf8");
  const baseline = JSON.parse(
    await readFile(path.resolve(process.cwd(), "evals/f3-decision-baseline.json"), "utf8"),
  ) as {
    fixtureSha256: string;
    implementationSha256: string;
    implementationScopeVersion: string;
    protocolVariant: string;
    metrics: {
      total: number;
      accuracy: number;
      decisionCoverage: number;
      probeRecall: number;
      falseProbeRate: number;
    };
    followUpRelevanceAudit: { artifact: string; sampleCount: number; relevanceRate: number };
    passed: boolean;
  };
  const digest = createHash("sha256").update(fixtureRaw).digest("hex");
  assert.equal(baseline.fixtureSha256, digest, "fixture 变更后必须重跑真实模型基线");
  assert.equal(
    baseline.implementationSha256,
    await f3ImplementationSha256(),
    "F3 关键实现变更后必须重跑真实模型基线",
  );
  assert.equal(baseline.implementationScopeVersion, F3_IMPLEMENTATION_SCOPE_VERSION);
  assert.equal(baseline.protocolVariant, "one_step_question_arg");
  assert.equal(baseline.metrics.total, 50);
  assert.ok(baseline.metrics.accuracy >= 0.85);
  assert.equal(baseline.metrics.decisionCoverage, 1);
  assert.ok(baseline.metrics.probeRecall >= 0.85);
  assert.ok(baseline.metrics.falseProbeRate <= 0.15);
  assert.equal(baseline.passed, true);

  const audit = JSON.parse(
    await readFile(path.resolve(process.cwd(), `evals/${baseline.followUpRelevanceAudit.artifact}`), "utf8"),
  ) as { sampleCount: number; relevantCount: number; relevanceRate: number; samples: unknown[] };
  assert.equal(audit.samples.length, audit.sampleCount);
  assert.equal(audit.relevantCount, audit.sampleCount);
  assert.ok(audit.relevanceRate >= 0.8);
});

test("一步协议性能基线绑定当前 fixture，p50 回归不超过 2.2 倍", async () => {
  const fixtureRaw = await readFile(path.resolve(process.cwd(), "evals/f3-decision-fixtures.json"), "utf8");
  const baseline = JSON.parse(
    await readFile(path.resolve(process.cwd(), "evals/f3-performance-baseline.json"), "utf8"),
  ) as {
    fixtureSha256: string;
    implementationSha256: string;
    implementationScopeVersion: string;
    protocolVariant: string;
    metrics: { decisionCoverage: number; retryRate: number; p50Ratio: number };
    passed: boolean;
  };
  assert.equal(baseline.fixtureSha256, createHash("sha256").update(fixtureRaw).digest("hex"));
  assert.equal(baseline.implementationSha256, await f3ImplementationSha256());
  assert.equal(baseline.implementationScopeVersion, F3_IMPLEMENTATION_SCOPE_VERSION);
  assert.equal(baseline.protocolVariant, "one_step_question_arg");
  assert.equal(baseline.metrics.decisionCoverage, 1);
  assert.equal(baseline.metrics.retryRate, 0);
  assert.ok(baseline.metrics.p50Ratio <= 2.2);
  assert.equal(baseline.passed, true);
});

test("最终一步协议长面基线绑定当前实现并满足完整结束条件", async () => {
  const baseline = JSON.parse(
    await readFile(path.resolve(process.cwd(), "evals/f3-long-interview-baseline.json"), "utf8"),
  ) as {
    sourceSessionId: string;
    protocolVariant: string;
    implementationSha256: string;
    implementationScopeVersion: string;
    dataClass: string;
    metrics: {
      durationSeconds: number;
      probeChains: number;
      decisionCount: number;
      candidateTurnCount: number;
      decisionCoverage: number;
      protocolErrorCount: number;
      finalStatus: string;
      finalPhase: string;
    };
    passed: boolean;
  };

  assert.equal(baseline.protocolVariant, "one_step_question_arg");
  assert.equal(baseline.implementationSha256, await f3ImplementationSha256());
  assert.equal(baseline.implementationScopeVersion, F3_IMPLEMENTATION_SCOPE_VERSION);
  assert.equal(baseline.dataClass, "repository-authored synthetic fixtures");
  assert.ok(baseline.metrics.durationSeconds >= 30 * 60);
  assert.ok(baseline.metrics.probeChains >= 8);
  assert.equal(baseline.metrics.decisionCount, baseline.metrics.candidateTurnCount);
  assert.equal(baseline.metrics.decisionCoverage, 1);
  assert.equal(baseline.metrics.protocolErrorCount, 0);
  assert.ok(["closing", "finished"].includes(baseline.metrics.finalStatus));
  assert.equal(baseline.metrics.finalPhase, "closing");
  assert.equal(baseline.passed, true);

  const audit = JSON.parse(
    await readFile(path.resolve(process.cwd(), "evals/f3-followup-relevance-audit.json"), "utf8"),
  ) as {
    sourceSessionId: string;
    protocolVariant: string;
    implementationSha256: string;
    implementationScopeVersion: string;
    sampleCount: number;
    relevantCount: number;
    relevanceRate: number;
  };
  assert.equal(audit.sourceSessionId, baseline.sourceSessionId);
  assert.equal(audit.protocolVariant, baseline.protocolVariant);
  assert.equal(audit.implementationSha256, baseline.implementationSha256);
  assert.equal(audit.implementationScopeVersion, F3_IMPLEMENTATION_SCOPE_VERSION);
  assert.equal(audit.relevantCount, audit.sampleCount);
  assert.ok(audit.sampleCount >= 8);
  assert.ok(audit.relevanceRate >= 0.8);
});
