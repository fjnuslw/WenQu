import assert from "node:assert/strict";
import test from "node:test";

import { grillSystemPrompt } from "../prompts.js";
import { buildGrillTools } from "./grill-repo.js";

const ROOT = process.cwd();

test("G1 v2 按 capability 动态收窄模型工具面", () => {
  const base = buildGrillTools(ROOT, {
    projectId: 7,
    apiBaseUrl: "http://127.0.0.1:23480",
    capabilities: {},
  });
  const mapOnly = buildGrillTools(ROOT, {
    projectId: 7,
    apiBaseUrl: "http://127.0.0.1:23480",
    capabilities: { repoMap: true },
  });
  const full = buildGrillTools(ROOT, {
    projectId: 7,
    apiBaseUrl: "http://127.0.0.1:23480",
    capabilities: { repoMap: true, semanticSearch: true, gitOwnership: true },
  });

  assert.deepEqual(base.all.map((tool) => tool.name), ["list_files", "read_file", "search_code"]);
  assert.deepEqual(mapOnly.all.map((tool) => tool.name), [
    "list_files",
    "read_file",
    "search_code",
    "get_repo_map",
  ]);
  assert.deepEqual(full.all.map((tool) => tool.name), [
    "list_files",
    "read_file",
    "search_code",
    "get_repo_map",
    "semantic_search",
    "get_git_ownership",
  ]);
  const prompt = grillSystemPrompt(4, full.all.map((tool) => tool.name));
  assert.match(prompt, /开场问题前必须先调用一次 get_repo_map/);
  assert.match(prompt, /提交量不能直接当作能力结论/);
});

test("semantic_search 工具保留文件行锚点并限制 limit", async () => {
  const originalFetch = globalThis.fetch;
  let requestBody: Record<string, unknown> | null = null;
  globalThis.fetch = async (_input, init) => {
    requestBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
    return new Response(
      JSON.stringify({
        mode: "semantic",
        hits: [
          {
            path: "src/retrieval.py",
            start_line: 10,
            end_line: 24,
            score: 0.9123,
            content: "async def semantic_search():\n    pass",
          },
        ],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };
  try {
    const tools = buildGrillTools(ROOT, {
      projectId: 7,
      apiBaseUrl: "http://127.0.0.1:23480/",
      capabilities: { semanticSearch: true },
    });
    const tool = tools.semanticSearch as unknown as {
      execute: (id: string, args: { query: string; limit?: number }) => Promise<{
        content: Array<{ text: string }>;
      }>;
    };
    const result = await tool.execute("call-1", { query: "向量检索", limit: 99 });
    const captured = requestBody as Record<string, unknown> | null;
    assert.equal(captured?.["limit"], 8);
    assert.match(result.content[0]?.text ?? "", /src\/retrieval\.py:10-24/);
    assert.match(result.content[0]?.text ?? "", /score=0\.912/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
