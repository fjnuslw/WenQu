"use client";

import { MessageSquare } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { agentsUrl } from "@/lib/api";

interface SessionItem {
  id: string;
  mode: string;
  persona: { role?: string; company?: string };
  turns: number;
  projectName: string | null;
  projectId: number | null;
  last_ts: string | null;
  alive: boolean;
}

/** 模拟面试会话的归属板块（spec 续十四：会话记录归位到各功能页）。 */
export function RecentInterviews() {
  const router = useRouter();
  const [items, setItems] = useState<SessionItem[] | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const response = await fetch(agentsUrl("/sessions"));
        if (!response.ok) return;
        const data = (await response.json()) as { items: SessionItem[] };
        setItems(data.items.filter((item) => item.mode === "mock").slice(0, 8));
      } catch {
        setItems([]);
      }
    })();
  }, []);

  if (items === null || items.length === 0) return null;

  return (
    <section className="mt-6">
      <h2 className="mb-3 text-sm font-semibold text-ink">最近面试</h2>
      <div className="space-y-2">
        {items.map((item) => (
          <Card key={item.id} className="card-hover cursor-pointer" onClick={() => router.push(`/interview/${item.id}`)}>
            <CardContent className="flex items-baseline gap-x-3 p-3.5">
              <span className="text-sm font-medium text-ink">
                {item.persona?.company ?? "自由练习"}
              </span>
              <span className="text-xs text-ink-dim">{item.persona?.role ?? ""}</span>
              <span className="text-xs text-ink-dim">{item.turns} 轮</span>
              <span className="ml-auto flex items-center gap-2 text-xs text-ink-faint">
                {item.alive ? <span className="text-ok">可继续</span> : "仅回放"}
                {item.last_ts ? new Date(item.last_ts).toLocaleString("zh-CN") : ""}
                <MessageSquare className="size-3.5" />
              </span>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}
