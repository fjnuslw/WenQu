"use client";

import { AlertTriangle, ArrowLeft, ChevronLeft, ChevronRight, Code2, ExternalLink, Inbox, Info, Link as LinkIcon, MessageCircleQuestion, RefreshCw, Route as RouteIcon, Search, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { CompanyLogo } from "@/components/company-logo";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { agentsUrl, apiFetch, ApiError } from "@/lib/api";
import { KIND_LABELS } from "@/lib/tags";
import { cn } from "@/lib/utils";

/** 深链来源上下文：记录「从哪个页面带着什么筛选进来」，仅挂载时取一次。 */
interface DeepLinkOrigin {
  from: string;
  node: string | null;
  slug: string | null;
  title: string | null;
  tag: string | null;
}

interface CompanyItem {
  id: number;
  name: string;
  logo: string | null;
  question_count: number;
  career_url: string | null;
  career_note: string | null;
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

/**
 * URL 参数是用户可编辑的，直接喂给筛选会打崩请求或静默无结果：
 * 岗位与题型做白名单校验，非法值一律回落为「不限」而非报错。
 */
function sanitizeEnum(raw: string | null, allowed: readonly string[]): string {
  return raw && allowed.includes(raw) ? raw : "";
}

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

/**
 * 深链来源条：从学习路径节点等入口跳转进来时，说明「你为什么看到这批题」，
 * 并给一条回程路径。没有它，用户会以为自己误入了随机筛选结果。
 */
function DeepLinkBanner({
  origin,
  onDismiss,
  onClear,
}: {
  origin: DeepLinkOrigin;
  onDismiss: () => void;
  onClear: () => void;
}) {
  const backHref = origin.slug ? `/paths/${origin.slug}${origin.node ? `#${origin.node}` : ""}` : null;
  return (
    <div className="relative overflow-hidden rounded-xl border border-accent/25 bg-surface-2/60">
      {/* 左侧光带：与主题背景的 radial glow 呼应，区别于普通卡片 */}
      <span aria-hidden className="absolute inset-y-0 left-0 w-[3px] bg-gradient-to-b from-accent-strong via-accent to-accent-violet" />
      <div className="flex items-center gap-3 py-3 pl-4 pr-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg border border-accent/25 bg-accent-soft text-accent">
          <RouteIcon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-faint">
            来自学习路径
          </p>
          <p className="truncate text-sm text-ink">
            {origin.title ?? "相关题目"}
            {origin.tag && (
              <span className="ml-2 text-xs text-ink-dim">
                · 已按标签「{origin.tag}」筛选
              </span>
            )}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {backHref && (
            <Link
              href={backHref}
              className="inline-flex items-center gap-1 rounded-md border border-line px-2.5 py-1 text-xs text-ink-dim transition-colors hover:border-accent hover:text-accent"
            >
              <ArrowLeft className="size-3" />
              回到节点
            </Link>
          )}
          <button
            onClick={onClear}
            className="rounded-md border border-line px-2.5 py-1 text-xs text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
          >
            清除筛选
          </button>
          <button
            onClick={onDismiss}
            aria-label="关闭来源提示"
            className="grid size-7 place-items-center rounded-md text-ink-faint transition-colors hover:bg-surface hover:text-ink"
          >
            <X className="size-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

export function QuestionsExplorer() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [list, setList] = useState<ListState>(INITIAL_LIST);
  const [companies, setCompanies] = useState<CompanyItem[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  // 深链初始化：学习路径节点等入口用 /bank?tag=X 直达，进页面即已筛选
  const [company, setCompany] = useState(() => searchParams.get("company") ?? "");
  const [track, setTrack] = useState(() => sanitizeEnum(searchParams.get("track"), TRACKS));
  const [kind, setKind] = useState(() => sanitizeEnum(searchParams.get("kind"), Object.keys(KIND_LABELS)));
  const [tag, setTag] = useState(() => searchParams.get("tag") ?? "");
  const [queryInput, setQueryInput] = useState(() => searchParams.get("q") ?? "");
  const query = useDebouncedValue(queryInput, 300); // 防抖：只有停顿才触发请求
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<(typeof PAGE_SIZES)[number]>(20);
  const [askingId, setAskingId] = useState<number | null>(null);
  // 来源上下文只在挂载时取一次：后续筛选变化会改写 URL，但不能把「我从哪来」冲掉
  const [origin, setOrigin] = useState<DeepLinkOrigin | null>(() => {
    const from = searchParams.get("from");
    if (!from) return null;
    return {
      from,
      node: searchParams.get("node"),
      slug: searchParams.get("slug"),
      title: searchParams.get("title"),
      tag: searchParams.get("tag"),
    };
  });

  // 筛选状态回写 URL：当前视图可分享、可刷新保持、可前进后退
  useEffect(() => {
    const params = new URLSearchParams();
    if (company) params.set("company", company);
    if (track) params.set("track", track);
    if (kind) params.set("kind", kind);
    if (tag) params.set("tag", tag);
    if (query) params.set("q", query);
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }, [company, track, kind, tag, query, pathname, router]);

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

  // 标签 chips 由真实计数驱动（归一后的 canonical 名）；只截掉尾部低频杂项（spec 续二十）
  const tagEntries: [string, number][] = stats
    ? Object.entries(stats.by_tag)
        .filter(([, count]) => count >= 20)
        .sort((a, b) => b[1] - a[1])
    : [];
  // 深链进来的标签可能是低频词，被上面 ≥20 的阈值截掉就看不到「选中态」了，强制插到最前
  const tagChips: [string, number][] =
    tag && !tagEntries.some(([name]) => name === tag)
      ? [[tag, stats?.by_tag[tag] ?? 0], ...tagEntries]
      : tagEntries;

  const showEmpty = list.loaded && !list.error && list.items.length === 0;
  // 当前选中公司的官方网申入口（题库页直达投递，spec 续十九）
  const activeCareer = company ? companies.find((item) => item.name === company) : undefined;
  const hasFilters = Boolean(company || track || kind || tag || query);
  const activeFilterCount = [company, track, kind, tag, query].filter(Boolean).length;

  return (
    <div className="space-y-4">
      {origin && <DeepLinkBanner origin={origin} onDismiss={() => setOrigin(null)} onClear={() => {
        setOrigin(null);
        setCompany("");
        setTrack("");
        setKind("");
        setTag("");
        setQueryInput("");
      }} />}

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

      {/* 公司 logo 横条（加大瓷片；带官方网申直达，见 spec 续十九） */}
      <Card className="p-3">
        <div className="flex items-center justify-between">
          <FacetLabel text="按厂商" />
          <span
            className="flex items-center gap-1 text-[11px] text-ink-faint"
            title="「网申 ↗」直达公司官方校招入口（2026-08 逐家核验存活）。秋招多为招满即止，批次与岗位以官网最新公告为准；谨防收费内推与保面骗局。"
          >
            <Info className="size-3" />
            网申 = 官方校招入口 · 27 届秋招进行中
          </span>
        </div>
        <div className="mt-1 flex gap-3 overflow-x-auto pb-1">
          <button
            onClick={() => setCompany("")}
            className={cn(
              "flex w-[104px] shrink-0 flex-col items-center gap-2 rounded-xl border px-2.5 py-3 transition-colors",
              company === "" ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong",
            )}
          >
            <span className="grid size-14 place-items-center rounded-lg bg-surface-2 text-sm font-semibold text-ink-dim">
              全部
            </span>
            <span className="text-xs text-ink-dim">不限厂商</span>
          </button>
          {companies
            .filter((item) => item.question_count > 0 || item.logo || item.career_url)
            .map((item) => (
              <div
                key={item.id}
                className={cn(
                  "flex w-[104px] shrink-0 flex-col items-center gap-1.5 rounded-xl border px-2.5 py-3 transition-colors",
                  company === item.name ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong",
                )}
              >
                {/* 按钮与网申链接平级（button 内不能嵌套 a） */}
                <button
                  onClick={() => setCompany((current) => (current === item.name ? "" : item.name))}
                  title={`${item.name} · ${item.question_count} 题`}
                  className="flex flex-col items-center gap-2"
                >
                  <CompanyLogo name={item.name} logo={item.logo} />
                  <span className="w-full truncate text-center text-xs text-ink-dim">{item.name}</span>
                  <span className="text-[11px] text-ink-faint">{item.question_count} 题</span>
                </button>
                {item.career_url && (
                  <a
                    href={item.career_url}
                    target="_blank"
                    rel="noreferrer"
                    title={item.career_note ?? `${item.name} 官方校招网申入口`}
                    className="inline-flex items-center gap-1 text-[11px] text-accent hover:underline"
                  >
                    <ExternalLink className="size-3" /> 网申
                  </a>
                )}
              </div>
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
          {tagChips.length === 0 && <span className="text-[11px] text-ink-faint">统计加载中…</span>}
          {tagChips.map(([name, count]) => (
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
          {hasFilters && (
            <button
              onClick={() => {
                setCompany("");
                setTrack("");
                setKind("");
                setTag("");
                setQueryInput("");
              }}
              className="mt-3 rounded-md border border-line px-4 py-1.5 text-xs text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
            >
              清除 {activeFilterCount} 项筛选
            </button>
          )}
        </Card>
      )}
      {list.items.length > 0 && (
        <>
          <div className="flex items-center justify-between text-xs text-ink-dim">
            <span className="flex items-center gap-3">
              共 {total} 题
              {hasFilters && (
                <button
                  onClick={() => {
                    setCompany("");
                    setTrack("");
                    setKind("");
                    setTag("");
                    setQueryInput("");
                  }}
                  className="inline-flex items-center gap-1 text-ink-faint transition-colors hover:text-ink"
                  title="清空当前所有筛选条件"
                >
                  <X className="size-3" />
                  清除 {activeFilterCount} 项筛选
                </button>
              )}
              {activeCareer?.career_url && (
                <a
                  href={activeCareer.career_url}
                  target="_blank"
                  rel="noreferrer"
                  title={activeCareer.career_note ?? `${activeCareer.name} 官方校招网申入口`}
                  className="inline-flex items-center gap-1 text-accent hover:underline"
                >
                  <ExternalLink className="size-3" /> {activeCareer.name} · 官方网申
                </a>
              )}
            </span>
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
                    <p className="text-[15px] leading-relaxed text-ink">{question.stem}</p>
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
