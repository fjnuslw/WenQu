"use client";

import { ArrowRight, RefreshCw, Sparkles } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import {
  NODE_KIND_LABEL,
  type PathListItem,
  type PathsListOut,
  type TodayPlanItem,
  accentClass,
  pathIcon,
} from "@/lib/paths";

export default function PathsPage() {
  const [data, setData] = useState<PathsListOut | null>(null);
  const [plan, setPlan] = useState<TodayPlanItem[]>([]);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setFetching(true);
    setError(null);
    try {
      const [list, today] = await Promise.all([
        apiFetch<PathsListOut>("/api/paths"),
        apiFetch<{ items: TodayPlanItem[] }>("/api/paths/plan/today"),
      ]);
      setData(list);
      setPlan(today.items);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setFetching(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto max-w-6xl p-8">
      <PageHeader
        title="学习路径"
        description="四条有序路径：大模型应用、大模型算法、大模型开发、大厂手撕算法。每个节点都有产出物与验收判据，学完能直接接进题库和复习队列。"
        extra={
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={fetching}>
            <RefreshCw className={fetching ? "size-4 animate-spin" : "size-4"} />
            刷新
          </Button>
        }
      />

      {data && (
        <div className="mb-6 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-ink-dim">
          <span>
            {data.items.length} 条路径 · {data.node_count} 个节点 · {data.resource_count} 个资源
          </span>
          <span>资源核验于 {data.verified_at || "—"}</span>
          <span className="text-ink-faint">
            star / license / 链接状态均取自官方接口，GPL 与 AGPL 仓库不收录
          </span>
        </div>
      )}

      {error && <p className="mb-4 text-sm text-danger">出错了：{error}</p>}

      {plan.length > 0 && (
        <Card className="mb-6 border-accent/30">
          <CardContent className="p-5">
            <div className="mb-3 flex items-center gap-2">
              <Sparkles className="size-4 text-accent" />
              <span className="text-sm font-semibold text-ink">今天该推进的</span>
              <span className="text-xs text-ink-dim">已订阅路径各自取下一个未完成节点</span>
            </div>
            <div className="space-y-2">
              {plan.map((item) => {
                const accent = accentClass(item.path.accent);
                return (
                  <Link
                    key={item.node.id}
                    href={`/paths/${item.path.slug}#${item.node.id}`}
                    className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 rounded-md border border-line bg-surface-2/60 px-3.5 py-2.5 transition-colors hover:border-line-strong"
                  >
                    <span className={`text-xs font-medium ${accent.text}`}>{item.path.title}</span>
                    {item.stage && <span className="text-xs text-ink-faint">{item.stage.title}</span>}
                    <span className="text-sm text-ink">{item.node.title}</span>
                    <span className="ml-auto text-xs text-ink-dim">
                      {NODE_KIND_LABEL[item.node.kind]} · {item.node.hours}h · 按每天{" "}
                      {item.daily_minutes} 分钟约 {item.estimated_days} 天
                    </span>
                  </Link>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      <div className={fetching ? "opacity-60 transition-opacity" : undefined}>
        {!data ? (
          <p className="text-sm text-ink-dim">加载中…</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {data.items.map((path) => (
              <PathCard key={path.slug} path={path} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PathCard({ path }: { path: PathListItem }) {
  const accent = accentClass(path.accent);
  const Icon = pathIcon(path.icon);
  return (
    <Card className="card-hover">
      <CardContent className="flex h-full flex-col p-5">
        <div className="flex items-start gap-3">
          <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${accent.soft}`}>
            <Icon className={`size-5 ${accent.text}`} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2">
              <h2 className="text-base font-semibold tracking-tight">{path.title}</h2>
              {path.enrollment && <Badge variant="ok">已订阅</Badge>}
            </div>
            <p className="mt-0.5 text-xs leading-relaxed text-ink-dim">{path.subtitle}</p>
          </div>
        </div>

        <div className="mt-3.5 h-1.5 overflow-hidden rounded-full bg-surface-2">
          <div
            className={`h-full rounded-full ${accent.bar}`}
            style={{ width: `${path.percent}%` }}
          />
        </div>
        <div className="mt-2 flex items-baseline gap-x-3 text-xs text-ink-dim">
          <span className={accent.text}>
            {path.done_nodes}/{path.total_nodes} 节点 · {path.percent}%
          </span>
          <span>剩余约 {path.remaining_hours} 小时</span>
        </div>

        {path.current_node && (
          <p className="mt-3 truncate text-xs text-ink-faint">
            下一个：{path.current_node.title}
          </p>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-dim">
          <span>{path.stage_count} 阶段</span>
          <span>{path.core_resources} 个必学资源</span>
          <span>{path.weeks}</span>
        </div>

        {path.outcomes.length > 0 && (
          <ul className="mt-3 space-y-1">
            {path.outcomes.slice(0, 3).map((outcome) => (
              <li key={outcome} className="flex gap-1.5 text-xs leading-relaxed text-ink-dim">
                <span className={`mt-1.5 size-1 shrink-0 rounded-full ${accent.bar}`} />
                <span>{outcome}</span>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-auto pt-4">
          <Link
            href={`/paths/${path.slug}`}
            className={`inline-flex items-center gap-1.5 text-sm font-medium ${accent.text} hover:underline`}
          >
            进入路径
            <ArrowRight className="size-4" />
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
