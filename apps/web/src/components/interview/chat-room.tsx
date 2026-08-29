"use client";

import { FileText, SendHorizonal } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { AssistantMarkdown } from "@/components/assistant/markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { agentsUrl, apiFetch } from "@/lib/api";
import { INTERVIEW_PHASES } from "@/lib/phases";
import { cn } from "@/lib/utils";

interface ChatMessage {
  role: "candidate" | "interviewer";
  text: string;
  /** 思考流全文（thinkingLevel 开启时由 thinking_delta 累积） */
  thinking: string;
  /** 思考耗时（秒）：本轮首个 text_delta 到达时结算 */
  thinkSeconds: number | null;
}

interface QuestionProgress {
  index: number;
  total: number;
  stem: string;
}

interface ReportScore {
  dimension: string;
  score: number;
  comment: string;
}

interface InterviewReport {
  summary: string;
  scores: ReportScore[];
  strengths: string[];
  weaknesses: string[];
  review_suggestions: string[];
}

/**
 * 面试室：消费 POST /agents/sessions/:id/turn 的 SSE 流（经 Next 同源代理）。
 * SSE 帧解析用字符串操作（data: 行），不引入 EventSource（其不支持 POST）。
 */
async function consumeTurnStream(
  response: Response,
  handlers: {
    onDelta: (delta: string) => void;
    onThinkingDelta: (delta: string) => void;
    onEvent: (event: Record<string, unknown>) => void;
  },
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
      } else if (parsed.type === "thinking_delta" && typeof parsed.delta === "string") {
        handlers.onThinkingDelta(parsed.delta);
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

function ThinkingTrace({
  thinking,
  thinkSeconds,
  compact = false,
}: {
  thinking: string;
  thinkSeconds: number | null;
  compact?: boolean;
}) {
  return (
    <details className="group mb-2">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs text-ink-faint transition-colors hover:text-ink-dim">
        <span className="inline-block transition-transform group-open:rotate-90">▸</span>
        已深度思考{thinkSeconds !== null ? `（${thinkSeconds.toFixed(1)}s）` : ""}
      </summary>
      <div
        className={cn(
          "mt-1.5 whitespace-pre-wrap border-l-2 border-line pl-2.5 leading-relaxed text-ink-faint",
          compact ? "text-[11px]" : "text-xs",
        )}
      >
        {thinking}
      </div>
    </details>
  );
}

function ThinkingPanel({
  text,
  streaming,
  seconds,
}: {
  text: string;
  streaming: boolean;
  seconds: number | null;
}) {
  return (
    <aside className="hidden min-h-0 flex-col rounded-[10px] border border-line bg-surface/60 lg:flex lg:h-full">
      <header className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="text-sm font-medium text-ink">思考过程</span>
        <Badge variant={streaming ? "accent" : "default"}>
          {streaming ? "思考中" : seconds !== null ? `${seconds.toFixed(1)}s` : "max 档"}
        </Badge>
      </header>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-4 py-3 text-[13px] leading-relaxed text-ink-dim">
        {text ? (
          <p className="whitespace-pre-wrap">
            {text}
            {streaming && <span className="stream-cursor" />}
          </p>
        ) : (
          <p className="text-xs leading-relaxed text-ink-faint">
            解答时模型以 max 档深度思考，过程会实时显示在这里——像看学长当场想题，帮你理解答题路径而不只是答案。
          </p>
        )}
      </div>
    </aside>
  );
}

function ReportPanel({ report }: { report: InterviewReport }) {
  return (
    <div className="mt-4 space-y-3 rounded-[10px] border border-accent/30 bg-accent-soft/40 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink">评分报告</h3>
        <Badge variant="accent">I1</Badge>
      </div>
      <p className="text-sm leading-relaxed text-ink">{report.summary}</p>
      <div className="grid gap-2 md:grid-cols-2">
        {report.scores.map((score) => (
          <div key={score.dimension} className="rounded-lg bg-surface-2 p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-ink-dim">{score.dimension}</span>
              <span className="text-sm font-semibold text-accent">{score.score}/5</span>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-ink-dim">{score.comment}</p>
          </div>
        ))}
      </div>
      {report.weaknesses.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-warn">失分点（回流复习队列）</div>
          <ul className="list-disc space-y-1 pl-5 text-xs text-ink-dim">
            {report.weaknesses.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {report.review_suggestions.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-ok">复习建议</div>
          <ul className="list-disc space-y-1 pl-5 text-xs text-ink-dim">
            {report.review_suggestions.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function ChatRoom({ sessionId }: { sessionId: string }) {
  const searchParams = useSearchParams();
  const isAnswerMode = searchParams.get("mode") === "answer";
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [phase, setPhase] = useState("opening");
  const [question, setQuestion] = useState<QuestionProgress | null>(null);
  const [followUpDepth, setFollowUpDepth] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<InterviewReport | null>(null);
  const [reportBusy, setReportBusy] = useState(false);
  const [panelIdx, setPanelIdx] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const thinkStartedAtRef = useRef<number | null>(null);

  const currentPhase = INTERVIEW_PHASES.find((p) => p.id === phase);

  // 答题模式：挂载即把题目发给解答助手（题目已在会话题单里，directors 会注入题干）
  const autoSentRef = useRef(false);
  useEffect(() => {
    if (!isAnswerMode || autoSentRef.current) return;
    autoSentRef.current = true;
    void send("请解答当前题目。");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 思考栏默认跟随最新有思考内容的消息；点击气泡可回看历史思考
  const lastThinkingIdx = (() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index]?.role === "interviewer" && messages[index]?.thinking) return index;
    }
    return null;
  })();
  const panelMessage = messages[panelIdx ?? lastThinkingIdx ?? -1];

  const scrollToEnd = useCallback(() => {
    requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }));
  }, []);

  async function generateReport() {
    setReportBusy(true);
    setError(null);
    try {
      const data = await apiFetch<{ report: InterviewReport }>(`/api/sessions/${sessionId}/report`, {
        method: "POST",
      });
      setReport(data.report);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setReportBusy(false);
    }
  }

  function settleThinking() {
    if (thinkStartedAtRef.current === null) return;
    const seconds = (Date.now() - thinkStartedAtRef.current) / 1000;
    thinkStartedAtRef.current = null;
    setMessages((current) => {
      const next = [...current];
      const last = next[next.length - 1];
      if (last?.role === "interviewer" && last.thinkSeconds === null) last.thinkSeconds = seconds;
      return next;
    });
  }

  async function send(forcedText?: string) {
    const text = (forcedText ?? draft).trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    if (!forcedText) setDraft("");
    setPanelIdx(null);
    setMessages((current) => [
      ...current,
      { role: "candidate", text, thinking: "", thinkSeconds: null },
      { role: "interviewer", text: "", thinking: "", thinkSeconds: null },
    ]);
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
          settleThinking(); // 首个正文增量 = 思考结束
          setMessages((current) => {
            const next = [...current];
            const last = next[next.length - 1];
            if (last?.role === "interviewer") last.text += delta;
            return next;
          });
          scrollToEnd();
        },
        onThinkingDelta: (delta) => {
          if (thinkStartedAtRef.current === null) thinkStartedAtRef.current = Date.now();
          setMessages((current) => {
            const next = [...current];
            const last = next[next.length - 1];
            if (last?.role === "interviewer") last.thinking += delta;
            return next;
          });
        },
        onEvent: (event) => {
          if (event.type === "phase" && typeof event.phase === "string") setPhase(event.phase);
          if (event.type === "followup" && typeof event.level === "number") setFollowUpDepth(event.level);
          if (event.type === "error") setError(String(event.message));
          if (
            event.type === "question" &&
            typeof event.index === "number" &&
            typeof event.total === "number" &&
            typeof event.stem === "string"
          ) {
            setQuestion({ index: event.index, total: event.total, stem: event.stem });
          }
        },
      });
      settleThinking();
    } catch (caught) {
      settleThinking();
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
      scrollToEnd();
    }
  }

  const chatColumn = (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{isAnswerMode ? "答题助手" : "面试室"}</h1>
          <p className="text-xs text-ink-faint">会话 {sessionId.slice(0, 8)}…</p>
        </div>
        <div className="flex items-center gap-3">
          {question && (
            <Badge variant="accent">
              题单 {question.index}/{question.total}
            </Badge>
          )}
          {followUpDepth > 0 && <Badge variant="warn">追问深度 {followUpDepth}</Badge>}
          <div className="flex items-center gap-2.5">
            <span className="text-xs text-ink-dim">{currentPhase?.label ?? phase}</span>
            <PhaseStepper current={phase} />
          </div>
        </div>
      </header>

      {question && (
        <div className="mb-3 rounded-lg border border-accent/30 bg-accent-soft/60 px-3.5 py-2.5">
          <div className="text-[11px] font-medium text-accent">
            当前题目（{question.index}/{question.total}）
          </div>
          <div className="mt-0.5 line-clamp-2 text-xs text-ink">{question.stem}</div>
        </div>
      )}

      <div className="flex-1 space-y-4 overflow-y-auto rounded-[10px] border border-line bg-surface/60 p-5">
        {messages.length === 0 && (
          <div className="pt-16 text-center">
            <p className="text-sm text-ink-dim">{isAnswerMode ? "正在深度思考并解答当前题目…" : "会话已创建，面试官在等你。"}</p>
            <p className="mt-1 text-xs text-ink-faint">
              {isAnswerMode ? "思考过程会在右侧栏实时展示。" : "用一句自我介绍开场，面试官会从题单出第一题。"}
            </p>
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
            <div
              key={index}
              className="bubble-in mr-auto flex max-w-[92%] items-start gap-2.5"
              onClick={message.thinking ? () => setPanelIdx(index) : undefined}
            >
              <span className="brand-tile mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg text-[11px] font-semibold text-white">
                {isAnswerMode ? "助" : "考"}
              </span>
              <div className="min-w-0 flex-1 rounded-xl rounded-tl-sm bg-surface-2 px-4 py-3 text-sm leading-relaxed text-ink">
                {message.thinking && <ThinkingTrace thinking={message.thinking} thinkSeconds={message.thinkSeconds} />}
                {message.text ? (
                  <AssistantMarkdown text={message.text} streaming={busy && index === messages.length - 1} />
                ) : (
                  busy && <span className="stream-cursor" />
                )}
              </div>
            </div>
          ),
        )}
        <div ref={bottomRef} />
      </div>

      {error && <p className="mt-2 text-sm text-danger">出错了：{error}</p>}

      {report && <ReportPanel report={report} />}

      <div className="mt-4">
        <div className="flex gap-2">
          <Input
            className="h-10"
            placeholder={isAnswerMode ? "继续追问…" : "输入你的回答…"}
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
          {!isAnswerMode && (
            <Button
              variant="secondary"
              className="h-10"
              onClick={() => void generateReport()}
              disabled={reportBusy || report !== null}
              title={report ? "报告已生成" : "对本场面试生成评分报告"}
            >
              <FileText className="size-4" />
              {reportBusy ? "生成中…" : "评分报告"}
            </Button>
          )}
        </div>
        <p className="mt-2 text-center text-[11px] text-ink-faint">
          <span className="kbd">Enter</span> 发送 · {isAnswerMode ? "max 档深度思考 + 联网核实" : "阶段推进与追问深度由确定性状态机控制"} · 支持完整 markdown/公式渲染
        </p>
      </div>
    </div>
  );

  return (
    <div
      className={cn(
        "mx-auto flex h-full flex-col gap-4 p-6",
        isAnswerMode ? "max-w-6xl lg:grid lg:grid-cols-[minmax(0,1fr)_330px] lg:gap-5" : "max-w-3xl",
      )}
    >
      {chatColumn}
      {isAnswerMode && (
        <ThinkingPanel
          text={panelMessage?.role === "interviewer" ? (panelMessage.thinking ?? "") : ""}
          streaming={
            busy &&
            panelIdx === null &&
            panelMessage?.role === "interviewer" &&
            panelMessage.thinking.length > 0 &&
            panelMessage.text.length === 0
          }
          seconds={panelMessage?.role === "interviewer" ? (panelMessage.thinkSeconds ?? null) : null}
        />
      )}
    </div>
  );
}
