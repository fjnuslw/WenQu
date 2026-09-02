import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

/**
 * 会改变 F3 决策质量、协议安全或运行时接线的源文件集合。
 * 实模/性能/长面基线都绑定该签名，避免实现已变而陈旧证据仍显示通过。
 */
export const F3_IMPLEMENTATION_FILES: readonly string[] = [
  "src/types.ts",
  "src/session.ts",
  "src/server.ts",
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
