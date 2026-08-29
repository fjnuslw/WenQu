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

const GRADE_BUTTONS = [
  { grade: "forgot", label: "忘了", variant: "danger" as const, hint: "重学，明天再见" },
  { grade: "fuzzy", label: "模糊", variant: "secondary" as const, hint: "缩短间隔" },
  { grade: "mastered", label: "掌握了", variant: "default" as const, hint: "拉长间隔" },
];

export default function ReviewPage() {
  const [items, setItems] = useState<ReviewItemOut[] | null>(null);
  const [total, setTotal] = useState(0);
  const [scope, setScope] = useState<"due" | "all">("due");
  const [fetching, setFetching] = useState(false);
  const [gradingId, setGradingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setFetching(true);
    setError(null);
    try {
      const data = await apiFetch<{ total: number; items: ReviewItemOut[] }>(
        `/api/review?scope=${scope}&limit=100`,
      );
      setItems(data.items);
      setTotal(data.total);
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
