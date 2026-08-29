"use client";

import { AlertTriangle, ChevronLeft, ChevronRight, Code2, Inbox, Link as LinkIcon, MessageCircleQuestion, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { agentsUrl, apiFetch, ApiError } from "@/lib/api";
import { KIND_LABELS } from "@/lib/tags";
import { cn } from "@/lib/utils";

interface CompanyItem {
  id: number;
  name: string;
  logo: string | null;
  question_count: number;
}

interface SourceInfo {
  kind: "github" | "official" | "external" | null;
  repo: string | null;
  ref: string | null;
  channel: string | null;
  url: string | null;
}

interface QuestionItem {
  id: number;
  stem: string;
  kind: string;
  track: string | null;
  difficulty: number;
  answer: string | null;
  answer_provenance: string | null;
  source: SourceInfo;
  tags: string[];
  companies: { name: string; freq: number; logo: string | null }[];
}

interface QuestionsResponse {
  total: number;
  items: QuestionItem[];
}

interface Stats {
  total: number;
  by_track: Record<string, number>;
  by_kind: Record<string, number>;
  by_tag: Record<string, number>;
}

const TRACKS = ["大模型应用", "大模型算法", "大模型应用算法", "视觉算法", "通用基础"] as const;
const PAGE_SIZES = [20, 50, 100] as const;

const TRACK_CLASS: Record<string, string> = {
  大模型应用: "border-accent/40 bg-accent-soft text-accent",
  大模型算法: "border-accent-violet/40 bg-accent-violet/10 text-[#c4b0fd]",
  大模型应用算法: "border-ok/40 bg-ok/10 text-ok",
  视觉算法: "border-warn/40 bg-warn/10 text-warn",
  通用基础: "border-line bg-surface-2 text-ink-dim",
};

const KIND_TINTS: Record<string, BadgeVariant> = {
  knowledge: "default",
  handwritten_code: "warn",
  algorithm: "accent",
  scenario: "ok",
  behavior: "default",
};

type BadgeVariant = "default" | "accent" | "ok" | "warn" | "danger";

function DifficultyDots({ level }: { level: number }) {
  return (
    <span className="inline-flex items-center gap-0.5" title={`难度 ${level}/5`}>
      {[1, 2, 3, 4, 5].map((dot) => (
        <span
          key={dot}
          className={cn("size-1.5 rounded-full", dot <= level ? "bg-accent" : "bg-line-strong")}
        />
      ))}
    </span>
  );
}

/** 来源标记：GitHub 只显示仓库名不渲染外链（用户要求）；外渠道渲染可跳转链接。 */
function SourceChip({ source }: { source: SourceInfo }) {
  if (source.kind === "github") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] text-ink-faint">
        <Code2 className="size-3" /> {source.repo}
      </span>
    );
  }
  if (source.kind === "official") {
    return <span className="text-[11px] text-ink-faint">{source.repo}</span>;
  }
  if (source.kind === "external" && source.url) {
    return (
      <a
        href={source.url}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 text-[11px] text-accent hover:underline"
      >
        <LinkIcon className="size-3" /> {source.channel ?? "来源"}
      </a>
    );
  }
  return null;
}

function CompanyLogo({
  name,
  logo,
  size = "md",
}: {
  name: string;
  logo: string | null;
  size?: "sm" | "md";
}) {
  const box = size === "md" ? "size-11" : "size-4";
  if (logo) {
    return (
      <span className={cn("inline-block overflow-hidden rounded-md bg-white/95 p-0.5", box)}>
        <img src={logo} alt={name} className="size-full object-contain" />
      </span>
    );
  }
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center rounded-md bg-surface-2 text-sm font-semibold text-ink-dim",
        box,
      )}
    >
      {name.slice(0, 1)}
    </span>
  );
}

function FacetLabel({ text }: { text: string }) {
  return (
    <span className="mr-1 shrink-0 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-faint">
      {text}
    </span>
  );
}

/**
 * 数据/加载态分离（TanStack Query placeholderData 等价实现，见 search/前端性能优化调研.md）：
 * 拉取新数据期间保留旧列表并置灰，替代"清屏转圈"的闪烁。
 */
interface ListState {
  items: QuestionItem[];
  total: number;
  isFetching: boolean;
  loaded: boolean;
  error: string | null;
}

const INITIAL_LIST: ListState = { items: [], total: 0, isFetching: false, loaded: false, error: null };

export function QuestionsExplorer() {
  const router = useRouter();
  const [list, setList] = useState<ListState>(INITIAL_LIST);
  const [companies, setCompanies] = useState<CompanyItem[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [company, setCompany] = useState("");
  const [track, setTrack] = useState("");
  const [kind, setKind] = useState("");
  const [tag, setTag] = useState("");
  const [queryInput, setQueryInput] = useState("");
  const query = useDebouncedValue(queryInput, 300); // 防抖：只有停顿才触发请求
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<(typeof PAGE_SIZES)[number]>(20);
  const [askingId, setAskingId] = useState<number | null>(null);

  useEffect(() => {
    apiFetch<{ items: CompanyItem[] }>("/api/companies")
      .then((data) => setCompanies(data.items))
      .catch(() => setCompanies([]));
    apiFetch<Stats>("/api/questions/stats")
      .then(setStats)
      .catch(() => setStats(null));
  }, []);

  // 筛选变化回到第一页
  useEffect(() => {
    setPage(1);
  }, [company, track, kind, tag, query, pageSize]);

  const load = useCallback(
    (signal: AbortSignal) => {
      setList((current) => ({ ...current, isFetching: true, error: null }));
      const params = new URLSearchParams({ limit: String(pageSize), offset: String((page - 1) * pageSize) });
      if (company) params.set("company", company);
      if (track) params.set("track", track);
      if (kind) params.set("kind", kind);
      if (tag) params.set("tag", tag);
      if (query) params.set("q", query);
      apiFetch<QuestionsResponse>(`/api/questions?${params.toString()}`, { signal })
        .then((data) =>
          setList({ items: data.items, total: data.total, isFetching: false, loaded: true, error: null }),
        )
        .catch((error: unknown) => {
          if (signal.aborted) return;
          const message =
            error instanceof ApiError
              ? `${error.status} ${error.code}: ${error.message}`
              : error instanceof Error
                ? error.message
                : "未知错误";
          setList((current) => ({ ...current, isFetching: false, loaded: true, error: message }));
        });
    },
    [company, track, kind, tag, query, page, pageSize],
  );

  // 问答助手：二次确认后创建 answer 会话并跳转（websearch 闭环）
  async function askAssistant(question: QuestionItem) {
    const confirmed = window.confirm(
      `让 AI 解答助手回答这道题？（可联网搜索核实）

${question.stem.slice(0, 100)}${question.stem.length > 100 ? "…" : ""}`,
    );
    if (!confirmed) return;
    setAskingId(question.id);
    try {
      const response = await fetch(agentsUrl("/sessions"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "answer",
          persona: { role: "面试题解答助手" },
          maxQuestionsPerPhase: 4,
          maxFollowUpDepth: 4,
          questions: [{ id: question.id, stem: question.stem, kind: question.kind, answer: question.answer }],
        }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
        throw new ApiError(response.status, "create_failed", body?.error?.message ?? `创建会话失败: ${response.status}`);
      }
      const { id } = (await response.json()) as { id: string };
      router.push(`/interview/${id}?mode=answer`);
    } catch (caught) {
      alert(`问答助手启动失败：${caught instanceof Error ? caught.message : String(caught)}`);
    } finally {
      setAskingId(null);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const total = list.total;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const pageWindow = Array.from({ length: Math.min(5, totalPages) }, (_, index) => {
    const start = Math.max(1, Math.min(page - 2, totalPages - 4));
    return start + index;
  }).filter((value) => value >= 1 && value <= totalPages);

  // 标签 chips 由真实计数驱动（归一后的 canonical 名），只展示有题的
  const tagEntries = stats
    ? Object.entries(stats.by_tag)
        .filter(([, count]) => count > 0)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 18)
    : [];

  const showEmpty = list.loaded && !list.error && list.items.length === 0;

  return (
    <div className="space-y-4">
      {/* 搜索置顶：体感最关键的入口 */}
      <Card className="p-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-faint" />
          <Input
            className="h-10 pl-9 text-sm"
            placeholder="搜索题干：如 RAG、Agent、KV Cache、手撕 Attention…"
            value={queryInput}
            onChange={(event) => setQueryInput(event.target.value)}
          />
          {list.isFetching && (
            <RefreshCw className="absolute right-3 top-1/2 size-3.5 -translate-y-1/2 animate-spin text-ink-faint" />
          )}
        </div>
      </Card>

      {/* 公司 logo 横条（加大瓷片） */}
      <Card className="p-3">
        <FacetLabel text="按厂商" />
        <div className="flex gap-2.5 overflow-x-auto pb-1">
          <button
            onClick={() => setCompany("")}
            className={cn(
              "flex w-[88px] shrink-0 flex-col items-center gap-1.5 rounded-xl border px-2 py-2.5 transition-colors",
              company === "" ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong",
            )}
          >
            <span className="grid size-11 place-items-center rounded-lg bg-surface-2 text-sm font-semibold text-ink-dim">
              全部
            </span>
            <span className="text-[11px] text-ink-dim">不限厂商</span>
          </button>
          {companies
            .filter((item) => item.question_count > 0 || item.logo)
            .map((item) => (
              <button
                key={item.id}
                onClick={() => setCompany((current) => (current === item.name ? "" : item.name))}
                title={`${item.name} · ${item.question_count} 题`}
                className={cn(
                  "flex w-[88px] shrink-0 flex-col items-center gap-1.5 rounded-xl border px-2 py-2.5 transition-colors",
                  company === item.name ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong",
                )}
              >
                <CompanyLogo name={item.name} logo={item.logo} />
                <span className="w-full truncate text-center text-[11px] text-ink-dim">{item.name}</span>
                <span className="text-[10px] text-ink-faint">{item.question_count} 题</span>
              </button>
            ))}
        </div>
      </Card>

      {/* 岗位大类 + 题型 + 标签 */}
      <Card className="space-y-2.5 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <FacetLabel text="岗位" />
          <div className="flex items-center gap-1 rounded-lg bg-surface-2 p-1">
            {(["", ...TRACKS] as const).map((value) => (
              <button
                key={value || "all"}
                onClick={() => setTrack(value)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs transition-colors",
                  track === value ? "bg-accent-strong text-white" : "text-ink-dim hover:text-ink",
                )}
              >
                {value || "全部"}
                {value && stats?.by_track[value] !== undefined && (
                  <span className={cn("ml-1", track === value ? "text-white/70" : "text-ink-faint")}>
                    {stats.by_track[value]}
                  </span>
                )}
              </button>
            ))}
          </div>
          <span className="text-[11px] text-ink-faint">
            未分类 {stats ? (stats.by_track["未分类"] ?? 0) : "…"}（分类守护回填中）
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <FacetLabel text="题型" />
          {(["", ...Object.keys(KIND_LABELS)] as const).map((value) => (
            <Badge
              key={value || "all"}
              variant={kind === value ? "accent" : "default"}
              className="cursor-pointer select-none transition-colors hover:border-line-strong"
              onClick={() => setKind(value)}
            >
              {value ? KIND_LABELS[value] : "全部题型"}
              {value && stats?.by_kind[value] !== undefined && (
                <span className="ml-1 text-ink-faint">{stats.by_kind[value]}</span>
              )}
            </Badge>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <FacetLabel text="标签" />
          {tagEntries.length === 0 && <span className="text-[11px] text-ink-faint">统计加载中…</span>}
          {tagEntries.map(([name, count]) => (
            <Badge
              key={name}
              variant={tag === name ? "accent" : "default"}
              className="cursor-pointer select-none transition-colors hover:border-line-strong"
              onClick={() => setTag((current) => (current === name ? "" : name))}
            >
              {name}
              <span className="ml-1 text-ink-faint">{count}</span>
            </Badge>
          ))}
        </div>
      </Card>

      {list.error && (
        <Card className="border-danger/40 p-5 text-center">
          <AlertTriangle className="mx-auto mb-2 size-5 text-danger" />
          <p className="text-sm text-danger">加载失败：{list.error}</p>
          <button
            onClick={() => load(new AbortController().signal)}
            className="mt-3 rounded-md border border-line px-4 py-1.5 text-xs text-ink-dim hover:border-line-strong hover:text-ink"
          >
            重试
          </button>
        </Card>
      )}
      {showEmpty && (
        <Card className="p-10 text-center">
          <Inbox className="mx-auto mb-3 size-6 text-ink-faint" />
          <p className="text-sm text-ink-dim">当前筛选没有题目 —— 试试放宽条件，或等待后台导入。</p>
        </Card>
      )}
      {list.items.length > 0 && (
        <>
          <div className="flex items-center justify-between text-xs text-ink-dim">
            <span>共 {total} 题</span>
            <span className="flex items-center gap-2">
              每页
              {PAGE_SIZES.map((size) => (
                <button
                  key={size}
                  onClick={() => setPageSize(size)}
                  className={cn("rounded px-1.5 py-0.5", pageSize === size ? "bg-accent-soft text-accent" : "hover:text-ink")}
                >
                  {size}
                </button>
              ))}
              条
            </span>
          </div>
          {/* 拉取期间保留旧列表并置灰（keepPreviousData 等价） */}
          <div className={cn("space-y-2 transition-opacity", list.isFetching && "opacity-60")}>
            {list.items.map((question) => (
              <Card key={question.id} className="card-hover p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-sm leading-relaxed text-ink">{question.stem}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                      {question.track && (
                        <span
                          className={cn(
                            "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
                            TRACK_CLASS[question.track] ?? "",
                          )}
                        >
                          {question.track}
                        </span>
                      )}
                      <Badge variant={KIND_TINTS[question.kind] ?? "default"}>
                        {KIND_LABELS[question.kind] ?? question.kind}
                      </Badge>
                      {question.tags.map((name) => (
                        <Badge key={name}>{name}</Badge>
                      ))}
                      <DifficultyDots level={question.difficulty} />
                      {question.companies.map((company) => (
                        <span key={company.name} className="inline-flex items-center gap-1 text-[11px] text-ink-dim">
                          <CompanyLogo name={company.name} logo={company.logo} size="sm" />
                          {company.name}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-2">
                    <SourceChip source={question.source} />
                    <button
                      onClick={() => void askAssistant(question)}
                      disabled={askingId !== null}
                      className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[11px] text-ink-dim transition-colors hover:border-accent hover:text-accent disabled:opacity-40"
                      title="AI 解答助手（可联网搜索，支持追问）"
                    >
                      <MessageCircleQuestion className="size-3" />
                      {askingId === question.id ? "启动中…" : "问助手"}
                    </button>
                  </div>
                </div>
              </Card>
            ))}
          </div>
          {/* 分页器 */}
          <div className="flex items-center justify-between pt-1">
            <span className="text-xs text-ink-dim">
              第 {page} / {totalPages} 页
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                disabled={page <= 1}
                className="grid size-8 place-items-center rounded-md border border-line text-ink-dim hover:border-line-strong hover:text-ink disabled:opacity-40"
              >
                <ChevronLeft className="size-4" />
              </button>
              {pageWindow.map((value) => (
                <button
                  key={value}
                  onClick={() => setPage(value)}
                  className={cn(
                    "h-8 min-w-8 rounded-md border px-2 text-xs transition-colors",
                    value === page
                      ? "border-accent bg-accent-soft text-accent"
                      : "border-line text-ink-dim hover:border-line-strong hover:text-ink",
                  )}
                >
                  {value}
                </button>
              ))}
              {totalPages > 5 && page < totalPages - 2 && <span className="px-1 text-ink-faint">…</span>}
              {totalPages > 5 && page < totalPages - 2 && (
                <button
                  onClick={() => setPage(totalPages)}
                  className="h-8 min-w-8 rounded-md border border-line px-2 text-xs text-ink-dim hover:border-line-strong hover:text-ink"
                >
                  {totalPages}
                </button>
              )}
              <button
                onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                disabled={page >= totalPages}
                className="grid size-8 place-items-center rounded-md border border-line text-ink-dim hover:border-line-strong hover:text-ink disabled:opacity-40"
              >
                <ChevronRight className="size-4" />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
