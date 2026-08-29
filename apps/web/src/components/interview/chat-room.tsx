"use client";

import { SendHorizonal } from "lucide-react";
import { useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { agentsUrl } from "@/lib/api";
import { INTERVIEW_PHASES } from "@/lib/phases";
import { cn } from "@/lib/utils";

interface ChatMessage {
  role: "candidate" | "interviewer";
  text: string;
}

/**
 * 面试室：消费 POST /sessions/:id/turn 的 SSE 流。
 * SSE 帧解析用字符串操作（event:/data: 行），不引入 EventSource（其不支持 POST）。
 */
async function consumeTurnStream(
  response: Response,
  handlers: { onDelta: (delta: string) => void; onEvent: (event: Record<string, unknown>) => void },
): Promise<void> {
  const body = response.body;
  if (!body) throw new Error("响应无 body，无法流式读取");
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      const parsed = JSON.parse(data) as Record<string, unknown>;
      if (parsed.type === "text_delta" && typeof parsed.delta === "string") {
        handlers.onDelta(parsed.delta);
      } else {
        handlers.onEvent(parsed);
      }
    }
  }
}

function PhaseStepper({ current }: { current: string }) {
  const currentIndex = INTERVIEW_PHASES.findIndex((phase) => phase.id === current);
  return (
    <div className="flex items-center gap-1.5" title={INTERVIEW_PHASES.map((phase) => phase.label).join(" → ")}>
      {INTERVIEW_PHASES.map((phase, index) => (
        <span
          key={phase.id}
          className={cn(
            "h-1.5 rounded-full transition-all",
            index === currentIndex
              ? "w-5 bg-accent"
              : index < currentIndex
                ? "w-1.5 bg-ok/70"
                : "w-1.5 bg-line-strong",
          )}
        />
      ))}
    </div>
  );
}

export function ChatRoom({ sessionId }: { sessionId: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [phase, setPhase] = useState<string>("opening");
  const [followUpDepth, setFollowUpDepth] = useState<number>(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const currentPhase = INTERVIEW_PHASES.find((p) => p.id === phase);

  function scrollToEnd() {
    requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }));
  }

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    setDraft("");
    setMessages((current) => [...current, { role: "candidate", text }, { role: "interviewer", text: "" }]);
    scrollToEnd();

    try {
      const response = await fetch(agentsUrl(`/sessions/${sessionId}/turn`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
        throw new Error(body?.error?.message ?? `请求失败: ${response.status}`);
      }
      await consumeTurnStream(response, {
        onDelta: (delta) => {
          setMessages((current) => {
            const next = [...current];
            const last = next[next.length - 1];
            if (last?.role === "interviewer") last.text += delta;
            return next;
          });
          scrollToEnd();
        },
        onEvent: (event) => {
          if (event.type === "phase" && typeof event.phase === "string") setPhase(event.phase);
          if (event.type === "followup" && typeof event.level === "number") setFollowUpDepth(event.level);
          if (event.type === "error") setError(String(event.message));
        },
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
      scrollToEnd();
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col p-6">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">面试室</h1>
          <p className="text-xs text-ink-faint">会话 {sessionId.slice(0, 8)}…</p>
        </div>
        <div className="flex items-center gap-3">
          {followUpDepth > 0 && <Badge variant="warn">追问深度 {followUpDepth}</Badge>}
          <div className="flex items-center gap-2.5">
            <span className="text-xs text-ink-dim">{currentPhase?.label ?? phase}</span>
            <PhaseStepper current={phase} />
          </div>
        </div>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto rounded-[10px] border border-line bg-surface/60 p-5">
        {messages.length === 0 && (
          <div className="pt-20 text-center">
            <p className="text-sm text-ink-dim">会话已创建，面试官在等你。</p>
            <p className="mt-1 text-xs text-ink-faint">用一句自我介绍开场，或直接说「开始吧」。</p>
          </div>
        )}
        {messages.map((message, index) =>
          message.role === "candidate" ? (
            <div key={index} className="bubble-in ml-auto max-w-[80%]">
              <div className="rounded-xl rounded-tr-sm bg-accent-soft px-4 py-2.5 text-sm leading-relaxed text-ink">
                {message.text}
              </div>
            </div>
          ) : (
            <div key={index} className="bubble-in mr-auto flex max-w-[85%] items-start gap-2.5">
              <span className="brand-tile mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg text-[11px] font-semibold text-white">
                考
              </span>
              <div className="rounded-xl rounded-tl-sm bg-surface-2 px-4 py-2.5 text-sm leading-relaxed text-ink">
                {message.text || (busy ? <span className="stream-cursor" /> : "")}
              </div>
            </div>
          ),
        )}
        <div ref={bottomRef} />
      </div>

      {error && <p className="mt-2 text-sm text-danger">出错了：{error}</p>}

      <div className="mt-4">
        <div className="flex gap-2">
          <Input
            className="h-10"
            placeholder="输入你的回答…"
            value={draft}
            disabled={busy}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.nativeEvent.isComposing) void send();
            }}
          />
          <Button className="h-10 px-4" onClick={() => void send()} disabled={busy || draft.trim().length === 0}>
            <SendHorizonal className="size-4" />
          </Button>
        </div>
        <p className="mt-2 text-center text-[11px] text-ink-faint">
          <span className="kbd">Enter</span> 发送 · 阶段推进与追问深度由确定性状态机控制
        </p>
      </div>
    </div>
  );
}
