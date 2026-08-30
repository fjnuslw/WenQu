"use client";

import { ArrowRight, BookOpenCheck, Layers, MessagesSquare, Newspaper, RotateCcw, Swords } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

interface StatsOut {
  questions: { total: number; with_answer: number; by_track: Record<string, number> };
  experiences: { total: number };
  review: { total: number; due: number; mastered: number };
}

const MODULES = [
  {
    href: "/bank",
    title: "题库",
    desc: "大模型版 CodeTop：公司 × 岗位 × 频率榜，含手撕/算法与问助手",
    icon: Layers,
    tint: "text-accent bg-accent-soft",
    status: "K1",
  },
  {
    href: "/experiences",
    title: "面经",
    desc: "结构化「公司-岗位-轮次-问题树」，牛客话题页合规采集",
    icon: Newspaper,
    tint: "text-ok bg-ok/10",
    status: "K1",
  },
  {
    href: "/interview",
    title: "模拟面试",
    desc: "简历押题组卷 + 七阶段状态机 + 评分报告回流复习",
    icon: MessagesSquare,
    tint: "text-warn bg-warn/10",
    status: "I1",
  },
  {
    href: "/grilling",
    title: "项目拷打",
    desc: "读码备课 + 架构拷打 + 证据链报告：本平台的核心差异位",
    icon: Swords,
    tint: "text-danger bg-danger/10",
    status: "G1",
  },
] as const;

export default function DashboardPage() {
  const [stats, setStats] = useState<StatsOut | null>(null);

  useEffect(() => {
    void apiFetch<StatsOut>("/api/stats")
      .then(setStats)
      .catch(() => setStats(null));
  }, []);

  const cards = [
    { label: "题库", value: stats ? stats.questions.total.toLocaleString() : "…", hint: stats ? `${stats.questions.by_track["大模型应用"] ?? 0} 应用 · ${stats.questions.by_track["大模型算法"] ?? 0} 算法` : "" },
    { label: "结构化面经", value: stats ? String(stats.experiences.total) : "…", hint: "牛客/linux.do 采集" },
    { label: "待复习", value: stats ? String(stats.review.due) : "…", hint: stats ? `共 ${stats.review.total} 条 · 已掌握 ${stats.review.mastered}` : "" },
    { label: "覆盖岗位大类", value: stats ? String(Object.keys(stats.questions.by_track).length) : "…", hint: "应用/算法/应用算法/视觉/通用" },
  ];

  return (
    <div className="mx-auto max-w-5xl p-8">
      <PageHeader
        title="工作台"
        description="大模型应用 / Agent 求职备战：题库 × 面经 × 模拟面试 × 项目拷打 × 间隔复习。"
        extra={
          <Link href="/interview">
            <Button>
              开始一场模拟面试 <ArrowRight className="size-4" />
            </Button>
          </Link>
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {cards.map((card) => (
          <Card key={card.label} className="p-4">
            <div className="text-xs text-ink-dim">{card.label}</div>
            <div className="mt-1.5 text-2xl font-semibold tracking-tight">{card.value}</div>
            <div className="mt-1 text-xs text-ink-faint">{card.hint}</div>
          </Card>
        ))}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        {MODULES.map(({ href, title, desc, icon: Icon, tint, status }) => (
          <Link key={href} href={href}>
            <Card className="card-hover h-full">
              <CardContent className="flex h-full items-start gap-3.5 p-5">
                <span className={`grid size-10 shrink-0 place-items-center rounded-lg ${tint}`}>
                  <Icon className="size-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-ink">{title}</span>
                    <Badge variant="accent">{status}</Badge>
                  </div>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-ink-dim">{desc}</p>
                </div>
                <ArrowRight className="mt-1 size-4 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5" />
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BookOpenCheck className="size-4 text-accent" /> 今日复习队列
          </CardTitle>
          <Badge>SM-2</Badge>
        </CardHeader>
        <CardContent className="flex items-center justify-between py-3">
          <span className="text-ink-dim">
            {stats
              ? stats.review.due > 0
                ? `今日待复习 ${stats.review.due} 条——面试失分点自动回流，掌握了才拉长间隔。`
                : "今天没有到期的复习。去打一场模拟面试或项目拷打，失分点会自动回流。"
              : "加载中…"}
          </span>
          <Link href="/review" className="shrink-0">
            <Button variant="secondary" size="sm">
              <RotateCcw className="size-3.5" />
              去复习
            </Button>
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}
