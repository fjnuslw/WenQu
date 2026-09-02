import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

/**
 * F3 实模证据只绑定面试领域实现，不绑定承载多个产品模式的 server/session 壳。
 *
 * G1 曾仅为项目拷打增加 capability 字段，却让 F3 的真实模型基线失效；这说明
 * 原签名把共享接线误当成了 F3 行为。今后会改变 F3 决策、协议或提示词的实现
 * 必须落在 src/interview/ 内并进入本清单；共享壳由集成测试守护。
 */
export const F3_IMPLEMENTATION_SCOPE_VERSION = "f3-dedicated-v2";

export const F3_IMPLEMENTATION_FILES: readonly string[] = [
  "src/interview/contracts.ts",
  "src/interview/state-machine.ts",
  "src/interview/policy.ts",
  "src/interview/control-tools.ts",
  "src/interview/orchestrator.ts",
  "src/interview/prompts.ts",
  "src/interview/question-plan.ts",
  "src/interview/events.ts",
];

export async function f3ImplementationSha256(packageRoot = process.cwd()): Promise<string> {
  const hash = createHash("sha256");
  for (const relativePath of F3_IMPLEMENTATION_FILES) {
    const content = await readFile(path.resolve(packageRoot, relativePath));
    hash.update(relativePath);
    hash.update("\0");
    hash.update(content);
    hash.update("\0");
  }
  return hash.digest("hex");
}
