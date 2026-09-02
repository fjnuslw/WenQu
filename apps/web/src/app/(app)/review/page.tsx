"use client";

import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

interface ReviewItemOut {
  id: number;
  source: string;
  source_ref: string | null;
  question_text: string;
  weakness: string;
  tag: string | null;
  ease: number;
  interval_days: number;
  repetitions: number;
  lapses: number;
  due_on: string;
  overdue: boolean;
}

interface MasteryOut {
  total: number;
  mastered: number;
  learning: number;
  due: number;
  by_tag: Record<string, { total: number; mastered: number; learning: number; due: number }>;
}

const GRADE_BUTTONS = [
  { grade: "forgot", label: "忘了", variant: "danger" as const, hint: "重学，明天再见" },
  { grade: "fuzzy", label: "模糊", variant: "secondary" as const, hint: "缩短间隔" },
  { grade: "mastered", label: "掌握了", variant: "default" as const, hint: "拉长间隔" },
];

const SHOWCASE_SESSION = "README_SHOWCASE_SYNTHETIC_SESSION";

function showcaseMastery(items: ReviewItemOut[]): MasteryOut {
  const byTag: MasteryOut["by_tag"] = {};
  for (const item of items) {
    const tag = item.tag ?? "未分类";
    const stats = byTag[tag] ?? { total: 0, mastered: 0, learning: 0, due: 0 };
    stats.total += 1;
    stats.learning += 1;
    if (item.overdue) stats.due += 1;
    byTag[tag] = stats;
  }
  return { total: items.length, mastered: 0, learning: items.length, due: items.length, by_tag: byTag };
}

export default function ReviewPage() {
  const [items, setItems] = useState<ReviewItemOut[] | null>(null);
  const [mastery, setMastery] = useState<MasteryOut | null>(null);
  const [total, setTotal] = useState(0);
  const [scope, setScope] = useState<"due" | "all">("due");
  const [fetching, setFetching] = useState(false);
  const [gradingId, setGradingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showcaseMode, setShowcaseMode] = useState(false);

  const load = useCallback(async () => {
    setFetching(true);
    setError(null);
    try {
      const [data, masteryData] = await Promise.all([
        apiFetch<{ total: number; items: ReviewItemOut[] }>(`/api/review?scope=${scope}&limit=100`),
        apiFetch<MasteryOut>("/api/review/mastery"),
      ]);
      const showcase =
        typeof window !== "undefined" &&
        new URLSearchParams(window.location.search).get("showcase") === "1";
      const visibleItems = showcase
        ? data.items.filter((item) => item.source_ref === SHOWCASE_SESSION)
        : data.items;
      setShowcaseMode(showcase);
      setItems(visibleItems);
      setTotal(showcase ? visibleItems.length : data.total);
      setMastery(showcase ? showcaseMastery(visibleItems) : masteryData);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setFetching(false);
    }
  }, [scope]);

  useEffect(() => {
    void load();
  }, [load]);

  async function grade(id: number, grade: string) {
    setGradingId(id);
    setError(null);
    try {
      const updated = await apiFetch<ReviewItemOut>(`/api/review/${id}/grade`, {
        method: "POST",
        body: JSON.stringify({ grade }),
      });
      setItems((current) =>
        scope === "due"
          ? (current ?? []).filter((item) => item.id !== id) // 到期视图：评分即出队
          : (current ?? []).map((item) => (item.id === id ? updated : item)),
      );
      setTotal((value) => (scope === "due" ? Math.max(0, value - 1) : value));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setGradingId(null);
    }
  }

  return (
    <div className="mx-auto max-w-4xl p-8">
      <PageHeader
        title="复习队列"
        description="评分报告的失分点自动回流到这里，SM-2 间隔重复安排复习节奏——掌握了才拉长间隔。"
      />

      {showcaseMode && (
        <div className="mb-5 rounded-lg border border-accent/35 bg-accent-soft px-4 py-3 text-sm text-accent">
          README 安全演示模式：复习卡来自合成面试，不展示真实候选人的失分记录。
        </div>
      )}

      {mastery && mastery.total > 0 && (
        <Card className="mb-5">
          <CardContent className="p-5">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="text-sm font-semibold text-ink">掌握度</span>
              <span className="text-xs text-ink-dim">
                已掌握 {mastery.mastered} · 学习中 {mastery.learning} · 今日待复习 {mastery.due}
              </span>
              <a
                className="ml-auto text-xs text-accent hover:underline"
                href="/api/review/export.anki"
                download
              >
                导出 Anki 牌组（.apkg）
              </a>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-2">
              <div
                className="h-full rounded-full bg-ok/80"
                style={{ width: `${Math.round((mastery.mastered / mastery.total) * 100)}%` }}
              />
            </div>
            {Object.keys(mastery.by_tag).length > 0 && (
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
                {Object.entries(mastery.by_tag).map(([tag, stat]) => (
                  <span key={tag} className="text-xs text-ink-dim">
                    <span className="font-medium text-ink">{tag}</span> {stat.mastered}/{stat.total}
                  </span>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <div className="mb-5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          {(["due", "all"] as const).map((option) => (
            <button
              key={option}
              className={
                scope === option
                  ? "rounded-full border border-accent/60 bg-accent-soft px-3.5 py-1.5 text-xs font-medium text-accent"
                  : "rounded-full border border-line bg-surface-2 px-3.5 py-1.5 text-xs text-ink-dim hover:text-ink"
              }
              onClick={() => setScope(option)}
            >
              {option === "due" ? "今日待复习" : "全部"}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-ink-dim">
            {items ? `${scope === "due" ? `待复习 ${total}` : `共 ${total} 条`}` : "加载中…"}
          </span>
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={fetching}>
            <RefreshCw className={fetching ? "size-4 animate-spin" : "size-4"} />
            刷新
          </Button>
        </div>
      </div>

      {error && <p className="mb-4 text-sm text-danger">出错了：{error}</p>}

      {items && items.length === 0 && (
        <Card>
          <CardContent className="p-8 text-center text-sm text-ink-dim">
            {scope === "due"
              ? "今天没有到期复习。去打一场模拟面试，评分报告的失分点会自动回流到这里。"
              : "还没有复习条目。"}
          </CardContent>
        </Card>
      )}

      <div className={fetching ? "space-y-4 opacity-60 transition-opacity" : "space-y-4"}>
        {items?.map((item) => (
          <Card key={item.id} className="card-hover">
            <CardContent className="p-5">
              <div className="mb-2 flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
                <Badge variant={item.overdue ? "warn" : "accent"}>
                  {item.overdue ? "已逾期" : `到期 ${item.due_on}`}
                </Badge>
                <span className="text-xs text-ink-dim">
                  {[item.tag, `间隔 ${item.interval_days} 天`, `第 ${item.repetitions + 1} 次`,
                    ...(item.lapses > 0 ? [`遗忘 ${item.lapses} 次`] : [])].filter(Boolean).join(" · ")}
                </span>
                {item.source_ref && (
                  <span className="ml-auto text-xs text-ink-faint">会话 {item.source_ref.slice(0, 8)}…</span>
                )}
              </div>
              <p className="text-sm font-medium leading-relaxed text-ink">{item.question_text}</p>
              <p className="mt-1.5 text-xs leading-relaxed text-ink-dim">{item.weakness}</p>
              <div className="mt-3.5 flex items-center gap-2">
                {GRADE_BUTTONS.map((button) => (
                  <Button
                    key={button.grade}
                    variant={button.variant}
                    size="sm"
                    disabled={gradingId === item.id}
                    title={button.hint}
                    onClick={() => void grade(item.id, button.grade)}
                  >
                    {button.label}
                  </Button>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
