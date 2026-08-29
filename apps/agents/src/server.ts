/** HTTP + SSE 入口（spec §5.2）。 */

import { serve } from "@hono/node-server";
import { Hono } from "hono";
import { streamSSE } from "hono/streaming";
import { z } from "zod";

import { loadConfig } from "./config.js";
import { bootstrapPi } from "./pi.js";
import { AsyncQueue } from "./queue.js";
import { SessionManager, SessionNotFound } from "./session.js";
import type { ClientEvent } from "./types.js";

const config = loadConfig();
const runtime = bootstrapPi(config);
const manager = new SessionManager(runtime, config);

const personaSchema = z.object({
  company: z.string().optional(),
  role: z.string().min(1),
  style: z.string().optional(),
  jd: z.string().optional(),
  brief: z.string().optional(),
  resumeHighlights: z.array(z.string()).optional(),
});

const grillBriefingModuleSchema = z.object({
  files: z.array(z.string()).default([]),
  purpose: z.string(),
  tech_points: z.array(z.string()).default([]),
  detail_questions: z.array(z.string()).default([]),
  alternative_question: z.string().nullable().optional(),
  missing_question: z.string().nullable().optional(),
});

const grillSchema = z.object({
  projectId: z.number().int(),
  projectName: z.string().min(1),
  repoRoot: z.string().min(1),
  briefing: z.object({
    overview: z.string(),
    stack_summary: z.string(),
    modules: z.array(grillBriefingModuleSchema).default([]),
  }),
  claimChecks: z
    .array(
      z.object({
        claim: z.string(),
        status: z.string(),
        evidence: z.string().nullable().optional(),
        probe_question: z.string(),
      }),
    )
    .optional(),
  bankQuestions: z.array(z.string()).optional(),
  experienceProbes: z.array(z.string()).optional(),
});

const createSchema = z.object({
  mode: z.enum(["mock", "grill", "answer"]),
  persona: personaSchema,
  maxQuestionsPerPhase: z.number().int().min(1).max(10).default(4),
  maxFollowUpDepth: z.number().int().min(1).max(4).default(4),
  questions: z
    .array(
      z.object({
        id: z.number().int(),
        stem: z.string().min(1),
        kind: z.string(),
        answer: z
          .string()
          .nullable()
          .optional()
          .transform((value) => value ?? null),
        probes: z.array(z.string().min(1)).max(3).optional(),
      }),
    )
    .max(20)
    .optional(),
  grill: grillSchema.optional(),
});

const turnSchema = z.object({
  text: z.string().min(1),
  vagueAnswer: z.boolean().optional(),
});

function errorBody(code: string, message: string) {
  return { error: { code, message } };
}

const app = new Hono();

app.get("/health", (c) =>
  c.json({
    status: "ok",
    service: "agents",
    model: config.defaultModel,
    keyConfigured: config.hasApiKey,
  }),
);

app.post("/sessions", async (c) => {
  if (!config.hasApiKey) {
    return c.json(
      errorBody("not_configured", "DEEPSEEK_API_KEY 未配置：请在 apps/agents/.env 填写后重启服务"),
      503,
    );
  }
  const parsed = createSchema.safeParse(await c.req.json());
  if (!parsed.success) {
    return c.json(errorBody("validation_failed", parsed.error.issues.map(String).join("; ")), 422);
  }
  if (parsed.data.mode === "grill" && !parsed.data.grill) {
    return c.json(errorBody("validation_failed", "mode=grill 需要 grill 上下文（projectId/repoRoot/briefing）"), 422);
  }
  const id = await manager.create(parsed.data);
  return c.json({ id }, 201);
});

app.post("/sessions/:id/turn", async (c) => {
  const id = c.req.param("id");
  try {
    manager.require(id);
  } catch (error) {
    if (error instanceof SessionNotFound) return c.json(errorBody("not_found", error.message), 404);
    throw error;
  }
  const rawBody = await c.req.text();
  console.log(`[turn] raw body (${rawBody.length} bytes):`, rawBody.slice(0, 240));
  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(rawBody);
  } catch {
    return c.json(errorBody("validation_failed", `body 不是合法 JSON: ${rawBody.slice(0, 120)}`), 400);
  }
  const parsed = turnSchema.safeParse(parsedJson);
  if (!parsed.success) {
    return c.json(errorBody("validation_failed", parsed.error.issues.map(String).join("; ")), 422);
  }

  return streamSSE(c, async (stream) => {
    const queue = new AsyncQueue<ClientEvent>();
    const pump = (async () => {
      try {
        const outcome = await manager.turn(id, parsed.data, (event) => queue.push(event));
        queue.push({ type: "final", outcome });
      } catch (error) {
        queue.push({
          type: "error",
          message: error instanceof Error ? error.message : "unknown error",
        });
      } finally {
        queue.close();
      }
    })();
    for await (const event of queue) {
      await stream.writeSSE({ event: event.type, data: JSON.stringify(event) });
    }
    await pump;
  });
});

app.get("/sessions/:id", (c) => {
  try {
    return c.json(manager.snapshot(c.req.param("id")));
  } catch (error) {
    if (error instanceof SessionNotFound) return c.json(errorBody("not_found", error.message), 404);
    throw error;
  }
});

function sessionAlive(id: string): boolean {
  try {
    manager.snapshot(id);
    return true;
  } catch {
    return false; // SessionNotFound = agents 重启后内存会话丢失（历史仍可回放）
  }
}

/** 会话列表（从 JSONL 文件扫描，含已过期的）：mode/persona/轮数/时间——供前端"继续/回放"。 */
app.get("/sessions", async (c) => {
  const { readdir, readFile } = await import("node:fs/promises");
  const path = await import("node:path");
  let files: string[] = [];
  try {
    files = (await readdir(config.dataDir)).filter((name) => name.endsWith(".jsonl"));
  } catch {
    files = [];
  }
  const items = await Promise.all(
    files.map(async (name) => {
      const id = name.replace(/\.jsonl$/, "");
      const filePath = path.join(config.dataDir, name);
      let mode = "unknown";
      let persona: Record<string, unknown> = {};
      let turns = 0;
      let projectName: string | null = null;
      let grillProjectId: number | null = null;
      let lastTs: string | null = null;
      try {
        const raw = await readFile(filePath, "utf8");
        for (const line of raw.split("\n")) {
          if (!line.trim()) continue;
          try {
            const entry = JSON.parse(line) as Record<string, unknown>;
            if (entry.type === "session_start") {
              const cfg = (entry.config ?? {}) as Record<string, unknown>;
              mode = String(cfg.mode ?? "unknown");
              persona = (cfg.persona ?? {}) as Record<string, unknown>;
              const grill = cfg.grill as { projectName?: string; projectId?: number } | undefined;
              projectName = grill?.projectName ?? null;
              grillProjectId = grill?.projectId ?? null;
            }
            if (entry.type === "assistant") turns += 1;
            if (typeof entry.ts === "string") lastTs = entry.ts;
          } catch {
            // 损坏行跳过（append-only 尾部残留）
          }
        }
      } catch {
        return null;
      }
      const alive = sessionAlive(id);
      return { id, mode, persona, turns, projectName, projectId: grillProjectId, last_ts: lastTs, alive };
    }),
  );
  const sorted = items
    .filter((item): item is NonNullable<typeof item> => item !== null)
    .sort((a, b) => ((a.last_ts ?? "") < (b.last_ts ?? "") ? 1 : -1));
  return c.json({ items: sorted.slice(0, 30) });
});

/** 会话历史（JSONL 重放）：刷新页面/换设备后继续聊的前提是 agents 内存里会话仍存活。 */
app.get("/sessions/:id/history", async (c) => {
  const id = c.req.param("id");
  const { readFile } = await import("node:fs/promises");
  const path = await import("node:path");
  const filePath = path.join(config.dataDir, `${id}.jsonl`);
  let raw: string;
  try {
    raw = await readFile(filePath, "utf8");
  } catch {
    return c.json(errorBody("not_found", `会话日志不存在: ${id}`), 404);
  }
  const messages: { role: "candidate" | "interviewer"; text: string; thinking: string; thinkSeconds: number | null }[] = [];
  let thinkStartedAt: number | null = null;
  for (const line of raw.split("\n")) {
    if (!line.trim()) continue;
    try {
      const entry = JSON.parse(line) as Record<string, unknown>;
      if (entry.type === "user") {
        messages.push({ role: "candidate", text: String(entry.text ?? ""), thinking: "", thinkSeconds: null });
      } else if (entry.type === "assistant") {
        const ts = typeof entry.ts === "string" ? Date.parse(entry.ts) : null;
        let thinkSeconds: number | null = null;
        if (thinkStartedAt !== null && ts !== null) {
          thinkSeconds = Math.max(0, (ts - thinkStartedAt) / 1000);
        }
        messages.push({
          role: "interviewer",
          text: String(entry.text ?? ""),
          thinking: String(entry.thinking ?? ""),
          thinkSeconds,
        });
        thinkStartedAt = null;
      }
      if (entry.type === "user") thinkStartedAt = typeof entry.ts === "string" ? Date.parse(entry.ts) : null;
    } catch {
      // 损坏行跳过
    }
  }
  const alive = sessionAlive(id);
  return c.json({ id, alive, messages });
});

serve({ fetch: app.fetch, port: config.port }, (info) => {
  console.log(`[agents] listening on http://localhost:${info.port} (model: ${config.defaultModel})`);
});
