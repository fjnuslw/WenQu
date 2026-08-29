"use client";

import { History, MessageSquare } from "lucide-react";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { agentsUrl } from "@/lib/api";

interface SessionListItem {
  id: string;
  mode: string;
  persona: { role?: string; company?: string };
  turns: number;
  projectName: string | null;
  projectId: number | null;
  last_ts: string | null;
  alive: boolean;
}

const MODE_META: Record<string, { label: string; param?: string; variant: "accent" | "warn" | "ok" | "danger" }> = {
  grill: { label: "项目拷打", param: "grill", variant: "danger" },
  mock: { label: "模拟面试", variant: "accent" },
  answer: { label: "答题助手", param: "answer", variant: "ok" },
};

export default function SessionsPage() {
  const router = useRouter();
  const [items, setItems] = useState<SessionListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const response = await fetch(agentsUrl("/sessions"));
        if (!response.ok) throw new Error(`获取会话列表失败: ${response.status}`);
        const data = (await response.json()) as { items: SessionListItem[] };
        setItems(data.items);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    })();
  }, []);

  function open(item: SessionListItem) {
    const meta = MODE_META[item.mode];
    const params = new URLSearchParams();
    if (meta?.param) params.set("mode", meta.param);
    if (item.mode === "grill" && item.projectId !== null) params.set("project", String(item.projectId));
    const query = params.toString();
    router.push(`/interview/${item.id}${query ? `?${query}` : ""}`);
  }

  return (
    <div className="mx-auto max-w-4xl p-8">
      <PageHeader
        title="会话记录"
        description="所有面试/拷打/答题会话（agents JSONL 持久化）。刷新或重启后随时回来：可回放全部对话；服务未重启的会话还能继续聊。"
      />
      {error && <p className="mb-4 text-sm text-danger">出错了：{error}</p>}
      {items === null && !error && <p className="text-sm text-ink-dim">加载中…</p>}
      {items && items.length === 0 && (
        <Card>
          <CardContent className="p-8 text-center text-sm text-ink-dim">
            还没有会话。去「模拟面试」或「项目拷打」开一场。
          </CardContent>
        </Card>
      )}
      <div className="space-y-3">
        {items?.map((item) => {
          const meta = MODE_META[item.mode] ?? { label: item.mode, variant: "accent" as const };
          return (
            <Card key={item.id} className="card-hover cursor-pointer" onClick={() => open(item)}>
              <CardContent className="flex items-center gap-3 p-4">
                <span className="brand-tile grid size-9 shrink-0 place-items-center rounded-lg text-xs font-semibold text-white">
                  {meta.label.slice(0, 1)}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-ink">{meta.label}</span>
                    {item.persona?.company && <Badge>{item.persona.company}</Badge>}
                    {item.projectName && <Badge variant="accent">{item.projectName}</Badge>}
                    {item.alive ? (
                      <Badge variant="ok">可继续</Badge>
                    ) : (
                      <Badge variant="warn">仅回放</Badge>
                    )}
                  </div>
                  <p className="mt-0.5 text-[11px] text-ink-faint">
                    {item.persona?.role ?? "—"} · {item.turns} 轮
                    {item.last_ts ? ` · ${new Date(item.last_ts).toLocaleString("zh-CN")}` : ""}
                  </p>
                </div>
                <MessageSquare className="size-4 shrink-0 text-ink-faint" />
              </CardContent>
            </Card>
          );
        })}
      </div>
      <p className="mt-6 flex items-center gap-1.5 text-[11px] text-ink-faint">
        <History className="size-3" />
        会话日志存于 data/sessions/*.jsonl（append-only，可审计），列表按最近活动排序。
      </p>
    </div>
  );
}
