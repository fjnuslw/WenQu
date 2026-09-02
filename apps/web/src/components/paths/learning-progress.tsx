"use client";

/** 工作台「学习路径」进度卡（F7 P2）。
 *
 * 设计原则：工作台上这一屏要回答三个问题——**学到哪了 / 下一步做什么 / 还得多久**。
 * 未订阅时不显示空进度条（那只会制造焦虑），改为展示五条线的规模供挑选。
 */

import { ArrowRight, Clock3, Flame, Route as RouteIcon, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import {
  NODE_KIND_HINT,
  NODE_KIND_LABEL,
  accentClass,
  pathIcon,
  type PathListItem,
  type PathsListOut,
  type TodayPlanItem,
} from "@/lib/paths";
import { cn } from "@/lib/utils";

interface TodayPlanOut {
  items: TodayPlanItem[];
}

/** 环形进度：比条形更省空间，数字放中心一眼可读。 */
function ProgressRing({
  percent,
  barClass,
  size = 44,
}: {
  percent: number;
  barClass: string;
  size?: number;
}) {
  const radius = (size - 6) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.min(100, Math.max(0, percent));
  const offset = circumference * (1 - clamped / 100);
  const center = size / 2;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
      <circle
        cx={center}
        cy={center}
        r={radius}
        fill="none"
        strokeWidth="3"
        className="stroke-line"
      />
      <circle
        cx={center}
        cy={center}
        r={radius}
        fill="none"
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform={`rotate(-90 ${center} ${center})`}
        className={cn("stroke-current transition-[stroke-dashoffset] duration-500", barClass)}
      />
    </svg>
  );
}

function LoadingSkeleton() {
  return (
    <Card className="mt-6 overflow-hidden">
      <div className="h-[3px] w-full bg-gradient-to-r from-accent-strong via-accent to-accent-violet opacity-60" />
      <div className="space-y-3 p-4">
        <div className="h-4 w-28 animate-pulse rounded bg-surface-2" />
        <div className="h-16 animate-pulse rounded-lg bg-surface-2" />
        <div className="h-8 animate-pulse rounded-md bg-surface-2" />
      </div>
    </Card>
  );
}

/** 未订阅态：不给进度（全是 0 只会劝退），给规模 + 一句话定位。 */
function PickPaths({ items }: { items: PathListItem[] }) {
  return (
    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((path) => {
        const Icon = pathIcon(path.icon);
        const accent = accentClass(path.accent);
        return (
          <Link key={path.slug} href={`/paths/${path.slug}`} className="group">
            <div
              className={cn(
                "flex h-full items-start gap-3 rounded-lg border border-line bg-surface-2/40 p-3 transition-colors",
                "hover:border-line-strong",
              )}
            >
              <span
                className={cn(
                  "grid size-9 shrink-0 place-items-center rounded-lg border",
                  accent.ring,
                  accent.soft,
                  accent.text,
                )}
              >
                <Icon className="size-[18px]" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink">{path.title}</p>
                <p className="mt-0.5 text-xs text-ink-faint">
                  {path.stage_count} 阶段 · {path.total_nodes} 节点 · {path.core_resources} 必学
                </p>
                <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-ink-dim">
                  {path.for_who}
                </p>
              </div>
              <ArrowRight className="mt-1 size-3.5 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5" />
            </div>
          </Link>
        );
      })}
    </div>
  );
}

/** 今日下一步：只给「下一个」——路径的价值是下一步明确，不是清单更长。 */
function NextUp({ item }: { item: TodayPlanItem }) {
  const accent = accentClass(item.path.accent);
  const Icon = pathIcon(
    item.path.slug === "llm-app"
      ? "Bot"
      : item.path.slug === "llm-algo"
        ? "Brain"
        : item.path.slug === "llm-dev"
          ? "ServerCog"
          : item.path.slug === "leetcode"
            ? "Terminal"
            : "Compass",
  );

  return (
    <Link
      href={`/paths/${item.path.slug}#${item.node.id}`}
      className="group block overflow-hidden rounded-lg border border-line bg-surface-2/50 transition-colors hover:border-line-strong"
    >
      <div className="flex items-center gap-3 p-3.5">
        <span
          className={cn(
            "grid size-10 shrink-0 place-items-center rounded-lg border",
            accent.ring,
            accent.soft,
            accent.text,
          )}
        >
          <Icon className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-faint">
              今日下一步
            </span>
            <span className={cn("truncate text-[11px]", accent.text)}>
              {item.path.title}
              {item.stage ? ` · ${item.stage.title}` : ""}
            </span>
          </div>
          <p className="mt-0.5 truncate text-sm font-medium text-ink">{item.node.title}</p>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-ink-faint">
            <span title={NODE_KIND_HINT[item.node.kind]}>
              <span className="mr-1 rounded bg-surface-2 px-1.5 py-0.5 text-ink-dim">
                {NODE_KIND_LABEL[item.node.kind]}
              </span>
              {NODE_KIND_HINT[item.node.kind]}
            </span>
            <span className="inline-flex items-center gap-1">
              <Clock3 className="size-3" />
              {item.node.hours} 小时 · 每天 {item.daily_minutes} 分钟 ≈ {item.estimated_days} 天
            </span>
          </div>
        </div>
        <ArrowRight className="size-4 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5" />
      </div>
    </Link>
  );
}

export function LearningProgress() {
  const [list, setList] = useState<PathsListOut | null>(null);
  const [plan, setPlan] = useState<TodayPlanItem[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    Promise.all([
      apiFetch<PathsListOut>("/api/paths"),
      apiFetch<TodayPlanOut>("/api/paths/plan/today"),
    ])
      .then(([paths, today]) => {
        if (!alive) return;
        setList(paths);
        setPlan(today.items ?? []);
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, []);

  // 接口不可用时整卡隐藏：工作台的其他模块不该被一个失败的接口拖成半屏报错
  if (failed) return null;
  if (!list) return <LoadingSkeleton />;

  const enrolled = list.items.filter((item) => item.enrollment !== null);
  const totalDone = enrolled.reduce((sum, item) => sum + item.done_nodes, 0);
  const totalNodes = enrolled.reduce((sum, item) => sum + item.total_nodes, 0);
  const totalHoursLeft = enrolled.reduce((sum, item) => sum + item.remaining_hours, 0);
  // 分母剔除 skipped（后端已如此），这里保持一致，避免「跳过刷进度」
  const overall = totalNodes ? Math.round((totalDone / totalNodes) * 100) : 0;

  return (
    <Card className="mt-6 overflow-hidden">
      {/* 顶部光带：与 body 的 radial glow 呼应，把这一块从统计卡里拎出来 */}
      <div className="h-[3px] w-full bg-gradient-to-r from-accent-strong via-accent to-accent-violet opacity-70" />

      <div className="flex items-center justify-between px-4 pt-3.5 pb-2">
        <h3 className="flex items-center gap-2 text-sm font-medium text-ink">
          <RouteIcon className="size-4 text-accent" />
          学习路径
          {enrolled.length > 0 && (
            <span className="text-[11px] font-normal text-ink-faint">
              已订阅 {enrolled.length} 条 · 剩 {totalHoursLeft} 小时
            </span>
          )}
        </h3>
        <div className="flex items-center gap-2">
          {enrolled.length > 0 && (
            <span className="relative grid size-9 place-items-center" title={`已订阅路径总进度 ${overall}%`}>
              <ProgressRing percent={overall} barClass="text-accent" size={36} />
              <span className="absolute text-[10px] font-semibold tabular-nums text-ink-dim">{overall}</span>
            </span>
          )}
          <Badge>{list.node_count} 节点</Badge>
          <Link href="/paths">
            <Button variant="ghost" size="sm">
              全部路径
              <ArrowRight className="size-3.5" />
            </Button>
          </Link>
        </div>
      </div>

      <div className="space-y-3 px-4 pb-4">
        {enrolled.length === 0 ? (
          <>
            <p className="flex items-start gap-2 text-xs leading-relaxed text-ink-dim">
              <Sparkles className="mt-0.5 size-3.5 shrink-0 text-accent" />
              还没有订阅路径。五条线共 {list.node_count} 个节点、{list.resource_count} 条已核验资源，
              每个节点都标好了「读哪个文件的哪一节」。挑一条主线开始，进度会出现在这里。
            </p>
            <PickPaths items={list.items} />
          </>
        ) : (
          <>
            {plan.length > 0 && (
              <div className="space-y-2">
                {plan.map((item) => (
                  <NextUp key={`${item.path.slug}-${item.node.id}`} item={item} />
                ))}
              </div>
            )}

            <div className="space-y-1.5">
              {enrolled.map((path) => {
                const accent = accentClass(path.accent);
                const Icon = pathIcon(path.icon);
                return (
                  <Link
                    key={path.slug}
                    href={`/paths/${path.slug}`}
                    className="group flex items-center gap-3 rounded-md px-2 py-1.5 transition-colors hover:bg-surface-2/60"
                  >
                    <Icon className={cn("size-4 shrink-0", accent.text)} />
                    <span className="w-24 shrink-0 truncate text-xs text-ink-dim group-hover:text-ink">
                      {path.title}
                    </span>
                    {/* 条形进度：比百分比更直观地反映「还剩多少」 */}
                    <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-line">
                      <span
                        className={cn("block h-full rounded-full transition-[width] duration-500", accent.bar)}
                        style={{ width: `${path.percent}%` }}
                      />
                    </span>
                    <span className="shrink-0 text-[11px] tabular-nums text-ink-faint">
                      {path.done_nodes}/{path.total_nodes}
                    </span>
                    <span className={cn("w-9 shrink-0 text-right text-[11px] font-medium tabular-nums", accent.text)}>
                      {path.percent}%
                    </span>
                  </Link>
                );
              })}
            </div>

            {totalDone === 0 && (
              <p className="flex items-center gap-1.5 text-[11px] text-ink-faint">
                <Flame className="size-3 text-warn" />
                还没有完成任何节点——从上面的「今日下一步」点进去，勾满验收判据即自动置为完成。
              </p>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
