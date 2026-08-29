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
  resumeHighlights: z.array(z.string()).optional(),
});

const createSchema = z.object({
  mode: z.enum(["mock", "grill"]),
  persona: personaSchema,
  maxQuestionsPerPhase: z.number().int().min(1).max(10).default(4),
  maxFollowUpDepth: z.number().int().min(1).max(4).default(4),
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
  const parsed = turnSchema.safeParse(await c.req.json());
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

serve({ fetch: app.fetch, port: config.port }, (info) => {
  console.log(`[agents] listening on http://localhost:${info.port} (model: ${config.defaultModel})`);
});
