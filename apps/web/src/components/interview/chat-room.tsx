"use client";

import { FileText, Mic, MicOff, SendHorizonal, Volume2, VolumeX } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { AssistantMarkdown } from "@/components/assistant/markdown";
import { FileBrowser } from "@/components/grill/file-browser";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { agentsUrl, apiFetch } from "@/lib/api";
import { INTERVIEW_PHASES } from "@/lib/phases";
import { useSpeechRecognition, useSpeechSynthesis } from "@/hooks/use-speech";
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

interface EvidenceRef {
  kind: "quote" | "code";
  quote: string;
  file: string | null;
  line: number | null;
}

interface ReportScore {
  dimension: string;
  score: number;
  comment: string;
  evidence: EvidenceRef[];
}

interface WeaknessItem {
  text: string;
  evidence: EvidenceRef[];
}

interface InterviewReport {
  summary: string;
  scores: ReportScore[];
  strengths: string[];
  weaknesses: WeaknessItem[];
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
          compact ? "text-xs" : "text-xs",
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
  bare = false,
}: {
  text: string;
  streaming: boolean;
  seconds: number | null;
  bare?: boolean;
}) {
  const body = (
    <>
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
    </>
  );
  if (bare) return body;
  return (
    <aside className="hidden min-h-0 flex-col rounded-[10px] border border-line bg-surface/60 lg:flex lg:h-full">
      <header className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="text-sm font-medium text-ink">思考过程</span>
        <Badge variant={streaming ? "accent" : "default"}>
          {streaming ? "思考中" : seconds !== null ? `${seconds.toFixed(1)}s` : "max 档"}
        </Badge>
      </header>
      {body}
    </aside>
  );
}

/** 证据链渲染：原话=引用块；代码位置=可点击（grill 会话跳侧栏定位）。 */
function EvidenceList({
  evidence,
  onOpenFileRef,
}: {
  evidence: EvidenceRef[];
  onOpenFileRef?: (path: string, line: number) => void;
}) {
  if (!evidence || evidence.length === 0) return null;
  return (
    <div className="mt-2 space-y-1.5">
      {evidence.map((ref, index) =>
        ref.kind === "code" && ref.file ? (
          <button
            key={index}
            type="button"
            className="block w-full rounded-md border border-line bg-surface px-2.5 py-1 text-left font-mono text-xs text-accent hover:border-accent/40"
            onClick={() => onOpenFileRef?.(ref.file as string, ref.line ?? 1)}
            title={onOpenFileRef ? "点击在侧栏打开并定位" : undefined}
          >
            {ref.file}
            {ref.line !== null && ref.line !== undefined ? `:${ref.line}` : ""}
          </button>
        ) : (
          <blockquote
            key={index}
            className="border-l-2 border-line-strong pl-2.5 text-xs leading-relaxed text-ink-faint"
          >
            {ref.quote}
          </blockquote>
        ),
      )}
    </div>
  );
}

function ReportPanel({
  report,
  onOpenFileRef,
}: {
  report: InterviewReport;
  onOpenFileRef?: (path: string, line: number) => void;
}) {
  return (
    <div className="mt-4 space-y-3 rounded-[10px] border border-accent/30 bg-accent-soft/40 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink">评分报告</h3>
        <Badge variant="accent">证据链</Badge>
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
            <EvidenceList evidence={score.evidence ?? []} onOpenFileRef={onOpenFileRef} />
          </div>
        ))}
      </div>
      {report.weaknesses.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-warn">失分点（回流复习队列）</div>
          <div className="space-y-2">
            {report.weaknesses.map((item, index) => (
              <div key={index}>
                <p className="text-xs leading-relaxed text-ink-dim">{item.text}</p>
                <EvidenceList evidence={item.evidence ?? []} onOpenFileRef={onOpenFileRef} />
              </div>
            ))}
          </div>
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
  const modeParam = searchParams.get("mode");
  const isAnswerMode = modeParam === "answer";
  const isGrillMode = modeParam === "grill";
  const showSidePanel = isAnswerMode || isGrillMode; // 思考栏：答题/拷打都开
  const grillProjectId = isGrillMode ? searchParams.get("project") : null;
  const [sideTab, setSideTab] = useState<"thinking" | "files">("thinking");
  const roomTitle = isAnswerMode ? "答题助手" : isGrillMode ? "项目拷打" : "面试室";
  const avatarChar = isAnswerMode ? "助" : isGrillMode ? "拷" : "考";
  const inputPlaceholder = isAnswerMode ? "继续追问…" : isGrillMode ? "回答拷打官…" : "输入你的回答…";
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
  const [sessionAlive, setSessionAlive] = useState(true);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const thinkStartedAtRef = useRef<number | null>(null);

  const currentPhase = INTERVIEW_PHASES.find((p) => p.id === phase);

  // 历史（刷新/回访继续）：JSONL 重放；alive=false 表示 agents 重启过 → 只读回放
  // 答题模式且无历史时自动发出首问；有历史则不重复发。
  const autoSentRef = useRef(false);
  useEffect(() => {
    void (async () => {
      let hasHistory = false;
      let aliveNow = true; // agents 重启后的会话只读，不自动发开场
      try {
        const response = await fetch(agentsUrl(`/sessions/${sessionId}/history`));
        if (response.ok) {
          const data = (await response.json()) as {
            alive: boolean;
            messages: ChatMessage[];
          };
          setSessionAlive(data.alive);
          aliveNow = data.alive;
          if (data.messages.length > 0) {
            setMessages(data.messages);
            hasHistory = true;
          }
        }
      } catch {
        // agents 不可达：新会话场景，不阻塞
      }
      const autoPrompt = isAnswerMode
        ? "请解答当前题目。"
        : isGrillMode
          ? "面试官您好，我是这个项目的作者，请开始拷打。"
          : null;
      if (autoPrompt && !hasHistory && !autoSentRef.current && aliveNow) {
        autoSentRef.current = true;
        void send(autoPrompt);
      }
      setHistoryLoaded(true);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // file:line 引用点击 → 侧栏文件 tab 打开定位
  const openFileRef = useCallback((path: string, line: number) => {
    setSideTab("files");
    window.dispatchEvent(new CustomEvent("wenqu:open-file", { detail: { path, line } }));
  }, []);

  // 语音（spec 续十七）：麦克风实时转写进输入框；TTS 朗读面试官回复（可开关）
  const speech = useSpeechRecognition((finalText) => {
    setDraft((current) => (current ? `${current} ${finalText}` : finalText));
  });
  const tts = useSpeechSynthesis();

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
      setMessages((current) => {
        const last = current[current.length - 1];
        if (last?.role === "interviewer" && last.text) tts.speak(last.text);
        return current;
      });
    }
  }

  const chatColumn = (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{roomTitle}</h1>
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
          <div className="text-xs font-medium text-accent">
            当前题目（{question.index}/{question.total}）
          </div>
          <div className="mt-0.5 line-clamp-2 text-xs text-ink">{question.stem}</div>
        </div>
      )}

      <div className="flex-1 space-y-4 overflow-y-auto rounded-[10px] border border-line bg-surface/60 p-5">
        {messages.length === 0 && (
          <div className="pt-16 text-center">
            <p className="text-sm text-ink-dim">{isGrillMode ? "拷打官正在读你的代码…" : isAnswerMode ? "正在深度思考并解答当前题目…" : "会话已创建，面试官在等你。"}</p>
            <p className="mt-1 text-xs text-ink-faint">
              {showSidePanel ? "思考过程会在右侧栏实时展示。" : "用一句自我介绍开场，面试官会从题单出第一题。"}
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
              <span className="brand-tile mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg text-xs font-semibold text-white">
                {avatarChar}
              </span>
              <div className="min-w-0 flex-1 rounded-xl rounded-tl-sm bg-surface-2 px-4 py-3 text-sm leading-relaxed text-ink">
                {message.thinking && <ThinkingTrace thinking={message.thinking} thinkSeconds={message.thinkSeconds} />}
                {message.text ? (
                  <AssistantMarkdown
                    text={message.text}
                    streaming={busy && index === messages.length - 1}
                    onOpenFileRef={isGrillMode && grillProjectId ? openFileRef : undefined}
                  />
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

      {historyLoaded && !sessionAlive && (
        <p className="mt-2 rounded-md border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
          该会话在服务重启后过期：可完整回放下方对话，但不能继续发送。要继续拷打请开新会话。
        </p>
      )}

      {report && (
        <ReportPanel report={report} onOpenFileRef={isGrillMode && grillProjectId ? openFileRef : undefined} />
      )}

      <div className="mt-4">
        <div className="flex gap-2">
          <Input
            className="h-10"
            placeholder={inputPlaceholder}
            value={draft}
            disabled={busy || (historyLoaded && !sessionAlive)}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.nativeEvent.isComposing) void send();
            }}
          />
          {speech.supported && (
            <Button
              variant={speech.listening ? "danger" : "secondary"}
              className="h-10 px-3"
              onClick={() => (speech.listening ? speech.stop() : speech.start())}
              title={speech.listening ? "停止录音（转写已进输入框，可编辑后发送）" : "按住思路说话：实时转写进输入框"}
            >
              {speech.listening ? <MicOff className="size-4 animate-pulse" /> : <Mic className="size-4" />}
            </Button>
          )}
          {tts.supported && (
            <Button
              variant={tts.enabled ? "default" : "secondary"}
              className="h-10 px-3"
              onClick={() => tts.setEnabled((value) => !value)}
              title={tts.enabled ? "朗读已开：面试官回复自动语音播报，点此关闭" : "开启语音播报（面试官回复朗读）"}
            >
              {tts.enabled ? <Volume2 className="size-4" /> : <VolumeX className="size-4" />}
            </Button>
          )}
          <Button
            className="h-10 px-4"
            onClick={() => void send()}
            disabled={busy || draft.trim().length === 0 || (historyLoaded && !sessionAlive)}
          >
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
        {(speech.listening || speech.error) && (
          <p className={`mt-2 text-xs ${speech.error ? "text-danger" : "text-accent"}`}>
            {speech.error ?? (speech.interim ? `识别中：${speech.interim}` : "聆听中…（说完点麦克风停止，转写可编辑）")}
          </p>
        )}
        <p className="mt-2 text-center text-xs text-ink-faint">
          <span className="kbd">Enter</span> 发送 · {isAnswerMode ? "max 档深度思考 + 联网核实" : isGrillMode ? "拷打官可实时读你的代码查证（只读工具面）" : "阶段推进与追问深度由确定性状态机控制"} · 支持完整 markdown/公式渲染
        </p>
      </div>
    </div>
  );

  return (
    <div
      className={cn(
        "mx-auto flex h-full flex-col gap-4 p-6",
        showSidePanel
          ? isGrillMode
            ? "max-w-[1400px] lg:grid lg:grid-cols-[minmax(0,1fr)_420px] lg:gap-5"
            : "max-w-6xl lg:grid lg:grid-cols-[minmax(0,1fr)_330px] lg:gap-5"
          : "max-w-3xl",
      )}
    >
      {chatColumn}
      {showSidePanel && (
        <aside className="hidden min-h-0 flex-col rounded-[10px] border border-line bg-surface/60 lg:flex lg:h-full">
          {isGrillMode ? (
            <>
              <div className="flex items-center gap-1 border-b border-line px-3 py-2">
                {(
                  [
                    { key: "thinking", label: "思考过程" },
                    { key: "files", label: "项目文件" },
                  ] as const
                ).map((option) => (
                  <button
                    key={option.key}
                    className={cn(
                      "rounded-md px-3 py-1 text-xs font-medium transition-colors",
                      sideTab === option.key
                        ? "bg-accent-soft text-accent"
                        : "text-ink-dim hover:bg-surface-2 hover:text-ink",
                    )}
                    onClick={() => setSideTab(option.key)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              {sideTab === "thinking" ? (
                <ThinkingPanel
                  bare
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
              ) : grillProjectId ? (
                <FileBrowser projectId={Number(grillProjectId)} />
              ) : (
                <p className="p-4 text-xs leading-relaxed text-ink-faint">
                  该会话缺少项目上下文（旧会话或未带 project 参数），文件浏览不可用。
                </p>
              )}
            </>
          ) : (
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
        </aside>
      )}
    </div>
  );
}
