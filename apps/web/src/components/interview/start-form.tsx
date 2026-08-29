"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { agentsUrl, apiFetch, ApiError } from "@/lib/api";

const TRACK_OPTIONS = ["大模型应用", "大模型算法", "大模型应用算法", "视觉算法"] as const;

interface PlanQuestion {
  id: number;
  stem: string;
  kind: string;
  answer: string | null;
}

export function InterviewStartForm() {
  const router = useRouter();
  const [role, setRole] = useState("大模型应用开发实习生");
  const [company, setCompany] = useState("");
  const [track, setTrack] = useState("");
  const [usePlan, setUsePlan] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      let questions: PlanQuestion[] | undefined;
      if (usePlan) {
        // 组卷：按公司/岗位大类从题库抽题（含手撕与算法）
        const plan = await apiFetch<{ questions: PlanQuestion[] }>("/api/interview/plan", {
          method: "POST",
          body: JSON.stringify({
            role,
            company: company || undefined,
            track: track || undefined,
            size: 8,
          }),
        });
        questions = plan.questions;
      }
      const response = await fetch(agentsUrl("/sessions"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "mock",
          persona: { role, ...(company ? { company } : {}) },
          maxQuestionsPerPhase: 4,
          maxFollowUpDepth: 4,
          questions,
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
            目标公司（影响面试官风格与组卷频率榜）
          </label>
          <Input
            id="company"
            placeholder="如：字节跳动 / 阿里巴巴 / DeepSeek"
            value={company}
            onChange={(event) => setCompany(event.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs text-ink-dim" htmlFor="track">
            岗位大类（组卷侧重）
          </label>
          <select
            id="track"
            value={track}
            onChange={(event) => setTrack(event.target.value)}
            className="h-9 w-full rounded-md border border-line bg-surface px-3 text-sm text-ink focus:border-accent focus:outline-none"
          >
            <option value="">不限</option>
            {TRACK_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>
        <label className="flex items-center gap-2 text-xs text-ink-dim">
          <input
            type="checkbox"
            checked={usePlan}
            onChange={(event) => setUsePlan(event.target.checked)}
            className="size-3.5 accent-[#4f6ef7]"
          />
          从题库生成题单（按公司频率榜组卷，含手撕/算法）
        </label>
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
