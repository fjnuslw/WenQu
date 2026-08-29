import { ArrowRight, BookOpenCheck, Layers, MessagesSquare, Newspaper, Swords } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const MODULES = [
  {
    href: "/bank",
    title: "题库",
    desc: "大模型版 CodeTop：公司 × 岗位 × 频率榜，K1 正在灌入 3000+ 题",
    icon: Layers,
    tint: "text-accent bg-accent-soft",
    status: "K1",
  },
  {
    href: "/experiences",
    title: "面经",
    desc: "结构化「公司-岗位-轮次-问题树」，牛客/linux.do 合规采集",
    icon: Newspaper,
    tint: "text-ok bg-ok/10",
    status: "K1",
  },
  {
    href: "/interview",
    title: "模拟面试",
    desc: "七阶段状态机 + 4 级提示追问链，DeepSeek-V4 实测在即",
    icon: MessagesSquare,
    tint: "text-warn bg-warn/10",
    status: "I1",
  },
  {
    href: "/grilling",
    title: "项目拷打",
    desc: "读码拷打 + 证据链报告：本平台的核心差异位",
    icon: Swords,
    tint: "text-danger bg-danger/10",
    status: "G1",
  },
] as const;

const STATS = [
  { label: "题库", value: "0", hint: "K1 导入后更新" },
  { label: "结构化面经", value: "0", hint: "K1 采集后更新" },
  { label: "模拟面试场次", value: "—", hint: "I1 后记录" },
  { label: "待复习", value: "—", hint: "L1 后记录" },
] as const;

export default function DashboardPage() {
  return (
    <div className="mx-auto max-w-5xl p-8">
      <PageHeader
        title="工作台"
        description="大模型应用 / Agent 求职备战。架构按完整产品设计，模块按 spec §9 垂直切片点亮。"
        extra={
          <Link href="/interview">
            <Button>
              开始一场模拟面试 <ArrowRight className="size-4" />
            </Button>
          </Link>
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {STATS.map((stat) => (
          <Card key={stat.label} className="p-4">
            <div className="text-xs text-ink-dim">{stat.label}</div>
            <div className="mt-1.5 text-2xl font-semibold tracking-tight">{stat.value}</div>
            <div className="mt-1 text-xs text-ink-faint">{stat.hint}</div>
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
          <span className="text-ink-faint">
            L1 里程碑点亮：错题本与间隔重复队列将出现在这里，失分点自动回流。
          </span>
          <Link href="/bank" className="shrink-0">
            <Button variant="secondary" size="sm">
              去刷题
            </Button>
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}
