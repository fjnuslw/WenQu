/** 学习路径（F7）前端类型与展示映射。

类型与 `apps/api/src/getoffer/paths/router.py` 的输出保持一致；
accent / icon 由目录数据给出字符串，这里映射成**静态**的组件与类名，
避免 Tailwind 因动态类名而无法生成样式。
*/

import {
  BookOpen,
  Bot,
  Brain,
  Compass,
  GraduationCap,
  Route,
  ServerCog,
  Terminal,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export type NodeStatus = "todo" | "doing" | "done" | "skipped";
export type ResourcePriority = "core" | "optional" | "reference";
export type ResourceKind = "repo" | "course" | "doc" | "paper" | "book" | "site";
export type NodeKind = "learn" | "build" | "drill";

export interface PathResourceOut {
  id: string;
  title: string;
  url: string;
  kind: ResourceKind;
  priority: ResourcePriority;
  repo: string | null;
  stars: number | null;
  license: string | null;
  pushed_at: string | null;
  stale: boolean;
  internal: boolean;
  /** 项目本身是什么（一句话定义） */
  description: string;
  /** 节点级说明：这个资源为什么放这里（"为什么要读它"） */
  why: string;
  pins: ResourcePinOut[];
}

/** 资源锚点：把「去看这个项目」精确到「看这个文件的这一节」。 */
export interface ResourcePinOut {
  label: string;
  url: string;
  note: string;
}

export interface PathNodeOut {
  id: string;
  order: number;
  kind: NodeKind;
  title: string;
  objective: string;
  deliverable: string;
  acceptance: string[];
  hours: number;
  related: { tags: string[]; question_kind: string | null };
  resources: PathResourceOut[];
  status?: NodeStatus;
  note?: string;
}

export interface PathStageOut {
  id: string;
  order: number;
  title: string;
  goal: string;
  weeks: string;
  node_count: number;
  done_count: number;
  hours: number;
  nodes: PathNodeOut[];
}

export interface PathSummary {
  total_nodes: number;
  done_nodes: number;
  skipped_nodes: number;
  percent: number;
  total_hours: number;
  remaining_hours: number;
  current_node: { id: string; title: string; kind: NodeKind } | null;
}

export interface PathEnrollment {
  path_slug: string;
  target_role: string;
  daily_minutes: number;
  started_on: string;
  target_on: string | null;
}

/** 路径元信息（目录数据字段，列表与详情共用）。 */
export interface PathMeta {
  slug: string;
  title: string;
  subtitle: string;
  order: number;
  accent: string;
  icon: string;
  for_who: string;
  weeks: string;
  outcomes: string[];
}

export interface PathListItem extends PathMeta {
  stage_count: number;
  core_resources: number;
  enrollment: PathEnrollment | null;
  total_nodes: number;
  done_nodes: number;
  skipped_nodes: number;
  percent: number;
  total_hours: number;
  remaining_hours: number;
  current_node: { id: string; title: string; kind: NodeKind } | null;
}

export interface PathsListOut {
  verified_at: string;
  resource_count: number;
  node_count: number;
  items: PathListItem[];
}

export interface PathDetailOut {
  path: PathMeta;
  summary: PathSummary;
  enrollment: PathEnrollment | null;
  verified_at: string;
  stages: PathStageOut[];
}

export interface TodayPlanItem {
  path: { slug: string; title: string; accent: string };
  stage: { id: string; title: string } | null;
  node: PathNodeOut;
  daily_minutes: number;
  estimated_days: number;
}

export const NODE_KIND_LABEL: Record<NodeKind, string> = {
  learn: "学",
  build: "做",
  drill: "练",
};

export const NODE_KIND_HINT: Record<NodeKind, string> = {
  learn: "读懂原理，建立认知",
  build: "动手产出可运行的东西",
  drill: "限时训练，形成肌肉记忆",
};

export const RESOURCE_KIND_LABEL: Record<ResourceKind, string> = {
  repo: "仓库",
  course: "课程",
  doc: "文档",
  paper: "论文",
  book: "书",
  site: "站点",
};

export const PRIORITY_LABEL: Record<ResourcePriority, string> = {
  core: "必学",
  optional: "选修",
  reference: "参考",
};

/** 优先级 → chip 静态类名（必须静态，否则 Tailwind 不生成样式）。 */
export const PRIORITY_CLASS: Record<ResourcePriority, string> = {
  core: "border-accent/40 bg-accent-soft text-accent",
  optional: "border-line bg-surface-2 text-ink-dim",
  reference: "border-line bg-transparent text-ink-faint",
};

/** 路径主色 → 静态类名组。 */
export const ACCENT_CLASS: Record<string, { ring: string; text: string; soft: string; bar: string }> = {
  violet: {
    ring: "border-accent-violet/40",
    text: "text-accent-violet",
    soft: "bg-accent-violet/10",
    bar: "bg-accent-violet",
  },
  blue: { ring: "border-accent/40", text: "text-accent", soft: "bg-accent-soft", bar: "bg-accent" },
  teal: { ring: "border-ok/40", text: "text-ok", soft: "bg-ok/10", bar: "bg-ok" },
  amber: { ring: "border-warn/40", text: "text-warn", soft: "bg-warn/10", bar: "bg-warn" },
  slate: { ring: "border-line-strong", text: "text-ink-dim", soft: "bg-surface-2", bar: "bg-line-strong" },
};

const ICONS: Record<string, LucideIcon> = {
  Route,
  Compass,
  Bot,
  Brain,
  ServerCog,
  Terminal,
  BookOpen,
  GraduationCap,
  Wrench,
};

export function pathIcon(name: string): LucideIcon {
  return ICONS[name] ?? Route;
}

export function accentClass(accent: string) {
  return ACCENT_CLASS[accent] ?? ACCENT_CLASS.slate;
}

/** 资源卡片的核验摘要，例如「129,676★ · MIT · 2026-08-17」。 */
export function resourceMeta(resource: PathResourceOut): string {
  if (resource.internal) {
    return "站内页面";
  }
  if (resource.stars === null) {
    return resource.kind === "paper" ? "论文" : "站点";
  }
  const parts = [`${resource.stars.toLocaleString("en-US")}★`];
  parts.push(resource.license ?? "未标注");
  if (resource.pushed_at) {
    parts.push(resource.pushed_at.slice(0, 10));
  }
  return parts.join(" · ");
}

/** GPL/AGPL 沿用 spec §10 门禁：清单里不应出现，出现即提示。 */
export function isCopyleft(license: string | null): boolean {
  if (!license) return false;
  const upper = license.toUpperCase();
  return upper.includes("GPL");
}
