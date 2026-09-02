"use client";

import {
  ArrowLeft,
  ArrowRight,
  Check,
  Circle,
  Layers,
  MapPin,
  RefreshCw,
  RotateCcw,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import {
  NODE_KIND_HINT,
  NODE_KIND_LABEL,
  PRIORITY_LABEL,
  RESOURCE_KIND_LABEL,
  type NodeStatus,
  type PathDetailOut,
  type PathNodeOut,
  type PathStageOut,
  accentClass,
  isCopyleft,
  pathIcon,
  resourceMeta,
} from "@/lib/paths";

const STATUS_OPTIONS: { value: NodeStatus; label: string }[] = [
  { value: "todo", label: "待开始" },
  { value: "doing", label: "进行中" },
  { value: "done", label: "已完成" },
  { value: "skipped", label: "跳过" },
];

export default function PathDetailPage() {
  const params = useParams<{ slug: string }>();
  const slug = params?.slug ?? "";
  const [data, setData] = useState<PathDetailOut | null>(null);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkedMap, setCheckedMap] = useState<Record<string, boolean[]>>({});
  const [busyNode, setBusyNode] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(
    async (slugValue: string) => {
      if (!slugValue) return;
      setFetching(true);
      setError(null);
      try {
        setData(await apiFetch<PathDetailOut>(`/api/paths/${slugValue}`));
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setFetching(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(slug);
  }, [slug, load]);

  async function setStatus(node: PathNodeOut, status: NodeStatus) {
    setBusyNode(node.id);
    setError(null);
    try {
      await apiFetch(`/api/paths/nodes/${node.id}/progress`, {
        method: "PUT",
        body: JSON.stringify({ status, note: "" }),
      });
      setData((current) => (current ? withNodeStatus(current, node.id, status) : current));
      if (status === "done") {
        setCheckedMap((current) => ({
          ...current,
          [node.id]: node.acceptance.map(() => true),
        }));
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusyNode(null);
    }
  }

  function toggleAcceptance(node: PathNodeOut, index: number) {
    const currentFlags =
      checkedMap[node.id] ?? (node.status === "done" ? node.acceptance.map(() => true) : node.acceptance.map(() => false));
    const next = currentFlags.map((flag, position) => (position === index ? !flag : flag));
    setCheckedMap((current) => ({ ...current, [node.id]: next }));

    const allChecked = next.length > 0 && next.every(Boolean);
    if (allChecked && node.status !== "done") {
      void setStatus(node, "done");
    } else if (!allChecked && node.status === "done") {
      void setStatus(node, "doing");
    }
  }

  async function toReview(node: PathNodeOut) {
    setBusyNode(node.id);
    setError(null);
    try {
      const result = await apiFetch<{ item_id: number; created: boolean }>(
        `/api/paths/nodes/${node.id}/review`,
        { method: "POST", body: "{}" },
      );
      setToast(result.created ? "已生成复习卡，进入复习队列" : "该节点的复习卡已存在");
      setTimeout(() => setToast(null), 2600);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusyNode(null);
    }
  }

  if (error) {
    return (
      <div className="mx-auto max-w-5xl p-8">
        <Link href="/paths" className="inline-flex items-center gap-1.5 text-sm text-ink-dim hover:text-ink">
          <ArrowLeft className="size-4" />
          返回学习路径
        </Link>
        <p className="mt-6 text-sm text-danger">出错了：{error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="mx-auto max-w-5xl p-8">
        <p className="text-sm text-ink-dim">加载中…</p>
      </div>
    );
  }

  const accent = accentClass(data.path.accent);
  const Icon = pathIcon(data.path.icon);

  return (
    <div className="mx-auto max-w-6xl p-8">
      <Link
        href="/paths"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-dim hover:text-ink"
      >
        <ArrowLeft className="size-4" />
        返回学习路径
      </Link>

      <PageHeader
        title={data.path.title}
        description={data.path.subtitle}
        extra={
          <Button variant="secondary" size="sm" onClick={() => void load(slug)} disabled={fetching}>
            <RefreshCw className={fetching ? "size-4 animate-spin" : "size-4"} />
            刷新
          </Button>
        }
      />

      <Card className="mb-6">
        <CardContent className="p-5">
          <div className="flex flex-wrap items-start gap-4">
            <span className={`grid size-11 shrink-0 place-items-center rounded-xl ${accent.soft}`}>
              <Icon className={`size-5 ${accent.text}`} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="h-2 overflow-hidden rounded-full bg-surface-2">
                <div
                  className={`h-full rounded-full ${accent.bar}`}
                  style={{ width: `${data.summary.percent}%` }}
                />
              </div>
              <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs text-ink-dim">
                <span className={accent.text}>
                  {data.summary.done_nodes}/{data.summary.total_nodes} 节点 · {data.summary.percent}%
                </span>
                <span>共 {data.summary.total_hours} 小时 · 剩余 {data.summary.remaining_hours} 小时</span>
                <span>参考周期 {data.path.weeks}</span>
              </div>
              {data.path.for_who && (
                <p className="mt-2 text-xs text-ink-faint">适合：{data.path.for_who}</p>
              )}
            </div>
          </div>

          <EnrollBar
            slug={slug}
            enrollment={data.enrollment}
            onSaved={(enrollment) => setData((current) => (current ? { ...current, enrollment } : current))}
          />
        </CardContent>
      </Card>

      {toast && (
        <div className="mb-4 rounded-md border border-ok/30 bg-ok/10 px-3.5 py-2 text-sm text-ok">
          {toast}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
        <nav className="lg:sticky lg:top-6 lg:self-start">
          <div className="mb-2 text-xs font-medium uppercase tracking-[0.14em] text-ink-faint">
            阶段
          </div>
          <ul className="space-y-1">
            {data.stages.map((stage) => (
              <li key={stage.id}>
                <a
                  href={`#${stage.id}`}
                  className="block rounded-md px-3 py-2 text-sm text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
                >
                  <span className="text-ink-faint">{stage.order}.</span> {stage.title}
                  <span className="mt-0.5 block text-xs text-ink-faint">
                    {stage.done_count}/{stage.node_count} 节点 · {stage.weeks}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="space-y-8">
          {data.stages.map((stage) => (
            <section key={stage.id} id={stage.id} className="scroll-mt-6">
              <div className="mb-3">
                <h2 className="flex items-baseline gap-2 text-base font-semibold tracking-tight">
                  <span className={`text-xs font-medium ${accent.text}`}>阶段 {stage.order}</span>
                  {stage.title}
                </h2>
                {stage.goal && (
                  <p className="mt-1 text-sm leading-relaxed text-ink-dim">{stage.goal}</p>
                )}
                <p className="mt-1 text-xs text-ink-faint">
                  {stage.node_count} 个节点 · {stage.hours} 小时 · {stage.weeks}
                </p>
              </div>

              <div className="space-y-3">
                {stage.nodes.map((node) => (
                  <NodeCard
                    key={node.id}
                    node={node}
                    slug={slug}
                    busy={busyNode === node.id}
                    checked={
                      checkedMap[node.id] ??
                      (node.status === "done"
                        ? node.acceptance.map(() => true)
                        : node.acceptance.map(() => false))
                    }
                    onToggle={(index) => toggleAcceptance(node, index)}
                    onStatus={(status) => void setStatus(node, status)}
                    onReview={() => void toReview(node)}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}

function withNodeStatus(data: PathDetailOut, nodeId: string, status: NodeStatus): PathDetailOut {
  const stages = data.stages.map((stage) => ({
    ...stage,
    nodes: stage.nodes.map((node) => (node.id === nodeId ? { ...node, status } : node)),
    done_count:
      stage.nodes.reduce(
        (count, node) => count + (node.id === nodeId ? (status === "done" ? 1 : 0) : node.status === "done" ? 1 : 0),
        0,
      ) || 0,
  }));
  const allNodes = stages.flatMap((stage) => stage.nodes);
  const done = allNodes.filter((node) => node.status === "done").length;
  const skipped = allNodes.filter((node) => node.status === "skipped").length;
  const denominator = allNodes.length - skipped;
  return {
    ...data,
    stages,
    summary: {
      ...data.summary,
      done_nodes: done,
      skipped_nodes: skipped,
      percent: denominator > 0 ? Math.round((done / denominator) * 100) : 0,
      remaining_hours: allNodes
        .filter((node) => node.status !== "done" && node.status !== "skipped")
        .reduce((sum, node) => sum + node.hours, 0),
      current_node:
        allNodes.find((node) => node.status !== "done" && node.status !== "skipped") ?? null,
    },
  };
}

function EnrollBar({
  slug,
  enrollment,
  onSaved,
}: {
  slug: string;
  enrollment: PathDetailOut["enrollment"];
  onSaved: (enrollment: NonNullable<PathDetailOut["enrollment"]>) => void;
}) {
  const [targetRole, setTargetRole] = useState(enrollment?.target_role ?? "");
  const [dailyMinutes, setDailyMinutes] = useState(enrollment?.daily_minutes ?? 60);
  const [targetOn, setTargetOn] = useState(enrollment?.target_on ?? "");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      const saved = await apiFetch<{ enrollment: NonNullable<PathDetailOut["enrollment"]> }>(
        `/api/paths/${slug}/enroll`,
        {
          method: "PUT",
          body: JSON.stringify({
            target_role: targetRole,
            daily_minutes: dailyMinutes,
            target_on: targetOn || null,
          }),
        },
      );
      onSaved(saved.enrollment);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-line pt-4">
      <label className="flex flex-col gap-1">
        <span className="text-xs text-ink-faint">目标岗位</span>
        <input
          value={targetRole}
          onChange={(event) => setTargetRole(event.target.value)}
          placeholder="如：字节大模型应用开发"
          className="h-8 w-52 rounded-md border border-line bg-surface-2 px-2.5 text-sm text-ink outline-none focus:border-accent"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs text-ink-faint">每天投入（分钟）</span>
        <input
          type="number"
          min={10}
          max={960}
          value={dailyMinutes}
          onChange={(event) => setDailyMinutes(Number(event.target.value))}
          className="h-8 w-24 rounded-md border border-line bg-surface-2 px-2.5 text-sm text-ink outline-none focus:border-accent"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs text-ink-faint">目标完成日</span>
        <input
          type="date"
          value={targetOn}
          onChange={(event) => setTargetOn(event.target.value)}
          className="h-8 w-40 rounded-md border border-line bg-surface-2 px-2.5 text-sm text-ink outline-none focus:border-accent"
        />
      </label>
      <Button size="sm" onClick={() => void save()} disabled={saving}>
        {enrollment ? "更新目标" : "订阅这条路径"}
      </Button>
      {enrollment && (
        <span className="text-xs text-ink-faint">
          订阅于 {enrollment.started_on}
          {enrollment.target_on ? ` · 目标 ${enrollment.target_on}` : ""}
        </span>
      )}
    </div>
  );
}

function NodeCard({
  node,
  slug,
  busy,
  checked,
  onToggle,
  onStatus,
  onReview,
}: {
  node: PathNodeOut;
  slug: string;
  busy: boolean;
  checked: boolean[];
  onToggle: (index: number) => void;
  onStatus: (status: NodeStatus) => void;
  onReview: () => void;
}) {
  const status = node.status ?? "todo";
  return (
    <Card id={node.id} className={`card-hover scroll-mt-6 ${status === "done" ? "opacity-75" : ""}`}>
      <CardContent className="p-5">
        <div className="mb-2.5 flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
          <Badge variant={status === "done" ? "ok" : status === "doing" ? "accent" : "default"}>
            {NODE_KIND_LABEL[node.kind]} · {node.acceptance.length} 条验收
          </Badge>
          <span className="text-xs text-ink-faint" title={NODE_KIND_HINT[node.kind]}>
            {NODE_KIND_HINT[node.kind]}
          </span>
          <span className="ml-auto text-xs text-ink-faint">{node.hours} 小时</span>
        </div>

        <h3 className="text-sm font-semibold leading-relaxed text-ink">{node.title}</h3>
        {node.objective && (
          <p className="mt-1.5 text-xs leading-relaxed text-ink-dim">{node.objective}</p>
        )}
        {node.deliverable && (
          <p className="mt-2 text-xs leading-relaxed text-ink">
            <span className="text-ink-faint">产出物 · </span>
            {node.deliverable}
          </p>
        )}

        {node.acceptance.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {node.acceptance.map((item, index) => (
              <li key={item}>
                <button
                  type="button"
                  onClick={() => onToggle(index)}
                  disabled={busy}
                  className="flex w-full items-start gap-2 text-left text-xs leading-relaxed text-ink-dim transition-colors hover:text-ink disabled:opacity-60"
                >
                  {checked[index] ? (
                    <Check className="mt-0.5 size-3.5 shrink-0 text-ok" />
                  ) : (
                    <Circle className="mt-0.5 size-3.5 shrink-0 text-ink-faint" />
                  )}
                  <span className={checked[index] ? "text-ink-faint line-through" : undefined}>
                    {item}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {node.resources.length > 0 && (
          <div className="mt-3.5 space-y-1.5">
            {node.resources.map((resource) => (
              <ResourceBlock key={resource.id} resource={resource} />
            ))}
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {STATUS_OPTIONS.map((option) => (
            <Button
              key={option.value}
              size="sm"
              variant={status === option.value ? "default" : "secondary"}
              disabled={busy}
              onClick={() => onStatus(option.value)}
            >
              {option.label}
            </Button>
          ))}
          <Button size="sm" variant="ghost" disabled={busy} onClick={onReview}>
            <RotateCcw className="size-3.5" />
            生成复习卡
          </Button>
          {node.related.tags.map((tag) => (
            <Link
              key={tag}
              href={`/bank?tag=${encodeURIComponent(tag)}&from=paths&node=${encodeURIComponent(node.id)}&slug=${encodeURIComponent(slug)}&title=${encodeURIComponent(node.title)}`}
              className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-xs text-ink-dim transition-colors hover:border-accent hover:text-accent"
              title={`在题库中筛选「${tag}」相关题目`}
            >
              <Layers className="size-3" />
              {tag}
            </Link>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function ResourceBlock({
  resource,
}: {
  resource: PathDetailOut["stages"][number]["nodes"][number]["resources"][number];
}) {
  const meta = resourceMeta(resource);
  const copyleft = isCopyleft(resource.license);
  const hasPins = resource.pins.length > 0;
  // 描述信息：「项目是什么」+「为什么放在这个节点」
  const hasAbout = resource.description || resource.why;
  const titleLink = resource.internal ? (
    <Link
      href={resource.url}
      className="text-[13px] font-medium text-ink-dim hover:text-ink hover:underline"
    >
      {resource.title}
    </Link>
  ) : (
    <a
      href={resource.url}
      target="_blank"
      rel="noreferrer"
      className="text-[13px] font-medium text-ink-dim hover:text-ink hover:underline"
    >
      {resource.title}
    </a>
  );
  return (
    <div className="rounded-md border border-line bg-surface-2/40 px-3.5 py-2.5">
      {/* 行 1：徽章 + 标题（弱化为标签）+ 元信息 */}
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <Badge variant={resource.priority === "core" ? "accent" : "default"}>
          {PRIORITY_LABEL[resource.priority]}
        </Badge>
        <span className="text-ink-dim">·</span>
        {titleLink}
        <span className="text-[11px] text-ink-faint">{RESOURCE_KIND_LABEL[resource.kind]}</span>
        <span className="text-[11px] text-ink-faint">·</span>
        <span className="text-[11px] text-ink-faint">{meta}</span>
        {resource.stale && <span className="text-[11px] text-warn">⚠ 可能过时</span>}
        {copyleft && <span className="text-[11px] text-danger">copyleft</span>}
      </div>

      {/* 行 2：项目说明 + 为什么放这里（核心「文字描述」） */}
      {hasAbout && (
        <div className="mt-1.5 text-[12px] leading-relaxed">
          {resource.description && (
            <span className="text-ink-dim">{resource.description}</span>
          )}
          {resource.description && resource.why && (
            <span className="mx-1.5 text-ink-faint">·</span>
          )}
          {resource.why && <span className="text-ink-faint">放这里：{resource.why}</span>}
        </div>
      )}

      {/* 行 3：锚点列表（真正的「点这些」） */}
      {hasPins && (
        <div className="mt-2.5 border-t border-line/60 pt-2">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] text-ink-faint">
            <MapPin className="size-3" />
            <span>在这里读 · {resource.pins.length} 个定位</span>
          </div>
          <ul className="space-y-1.5">
            {resource.pins.map((pin) => (
              <li key={pin.url}>
                <PinLink pin={pin} internal={resource.internal} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function PinLink({
  pin,
  internal,
}: {
  pin: PathDetailOut["stages"][number]["nodes"][number]["resources"][number]["pins"][number];
  internal: boolean;
}) {
  const className =
    "group inline-flex items-start gap-1.5 text-[11px] leading-relaxed text-ink-dim transition-colors hover:text-accent";
  const body = (
    <>
      <ArrowRight className="mt-0.5 size-3 shrink-0 text-ink-faint transition-colors group-hover:text-accent" />
      <span>
        <span className="hover:underline">{pin.label}</span>
        {pin.note && <span className="text-ink-faint">　—— {pin.note}</span>}
      </span>
    </>
  );
  return internal ? (
    <Link href={pin.url} className={className}>
      {body}
    </Link>
  ) : (
    <a href={pin.url} target="_blank" rel="noreferrer" className={className}>
      {body}
    </a>
  );
}
