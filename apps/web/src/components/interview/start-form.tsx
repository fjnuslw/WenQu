"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { AGENTS_URL, ApiError } from "@/lib/api";

export function InterviewStartForm() {
  const router = useRouter();
  const [role, setRole] = useState("大模型应用开发实习生");
  const [company, setCompany] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`${AGENTS_URL}/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "mock",
          persona: { role, ...(company ? { company } : {}) },
          maxQuestionsPerPhase: 4,
          maxFollowUpDepth: 4,
        }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
        throw new ApiError(response.status, "create_failed", body?.error?.message ?? `创建会话失败: ${response.status}`);
      }
      const { id } = (await response.json()) as { id: string };
      router.push(`/interview/${id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="max-w-xl">
      <CardHeader>
        <CardTitle>开始一场模拟面试</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 pt-1">
        <div className="space-y-1.5">
          <label className="text-xs text-ink-dim" htmlFor="role">
            目标岗位
          </label>
          <Input id="role" value={role} onChange={(event) => setRole(event.target.value)} />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs text-ink-dim" htmlFor="company">
            目标公司（可选，影响面试官追问风格）
          </label>
          <Input
            id="company"
            placeholder="如：字节 / 阿里 / DeepSeek"
            value={company}
            onChange={(event) => setCompany(event.target.value)}
          />
        </div>
        {error && (
          <p className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            启动失败：{error}
          </p>
        )}
        <Button className="w-full" onClick={start} disabled={busy || role.trim().length === 0}>
          {busy ? "创建会话中…" : "进入面试室"}
        </Button>
        <p className="text-center text-[11px] text-ink-faint">
          需要 apps/agents 在线（http://127.0.0.1:23481）并配置 DEEPSEEK_API_KEY
        </p>
      </CardContent>
    </Card>
  );
}
