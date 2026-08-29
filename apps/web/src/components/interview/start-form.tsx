"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

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
  probes?: string[];
}

interface PlanResponse {
  brief: string;
  resume_used: boolean;
  questions: PlanQuestion[];
}

interface ResumeListItem {
  id: number;
  file_name: string;
  candidate_name: string | null;
  role_target: string | null;
  highlights: string[];
}

export function InterviewStartForm() {
  const router = useRouter();
  const [role, setRole] = useState("大模型应用开发实习生");
  const [company, setCompany] = useState("");
  const [track, setTrack] = useState("");
  const [resumes, setResumes] = useState<ResumeListItem[]>([]);
  const [resumeId, setResumeId] = useState<number | null>(null);
  const [usePlan, setUsePlan] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void apiFetch<{ items: ResumeListItem[] }>("/api/resumes")
      .then((data) => {
        setResumes(data.items);
        if (data.items.length > 0) setResumeId(data.items[0].id);
      })
      .catch(() => setResumes([])); // 简历服务不可用时不阻塞面试入口
  }, []);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      let questions: PlanQuestion[] | undefined;
      let brief: string | undefined;
      let highlights: string[] | undefined;
      if (usePlan) {
        // 组卷 v2：公司频率榜 ∪ 简历考点押题 → LLM 定卷 + 面经追问素材
        const plan = await apiFetch<PlanResponse>("/api/interview/plan", {
          method: "POST",
          body: JSON.stringify({
            company: company || undefined,
            track: track || undefined,
            size: 8,
            resume_id: resumeId ?? undefined,
          }),
        });
        questions = plan.questions;
        brief = plan.brief || undefined;
        if (resumeId !== null) {
          const detail = await apiFetch<{ profile: { highlights?: string[] } }>(`/api/resumes/${resumeId}`);
          highlights = detail.profile.highlights;
        }
      }
      const response = await fetch(agentsUrl("/sessions"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "mock",
          persona: {
            role,
            ...(company ? { company } : {}),
            ...(brief ? { brief } : {}),
            ...(highlights?.length ? { resumeHighlights: highlights } : {}),
          },
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
          <label className="text-xs text-ink-dim" htmlFor="resume">
            简历（押题依据：结合简历考点与该公司面经组卷）
          </label>
          <select
            id="resume"
            value={resumeId ?? ""}
            onChange={(event) => setResumeId(event.target.value ? Number(event.target.value) : null)}
            className="h-9 w-full rounded-md border border-line bg-surface px-3 text-sm text-ink focus:border-accent focus:outline-none"
          >
            <option value="">不使用简历（纯题库组卷）</option>
            {resumes.map((resume) => (
              <option key={resume.id} value={resume.id}>
                {resume.candidate_name ? `${resume.candidate_name} · ` : ""}
                {resume.file_name}
              </option>
            ))}
          </select>
          {resumes.length === 0 && (
            <p className="text-[11px] text-ink-faint">
              还没有简历：先到「简历工作台」上传 PDF，面试官才能针对简历押题。
            </p>
          )}
        </div>
        <div className="space-y-1.5">
          <label className="text-xs text-ink-dim" htmlFor="role">
            目标岗位
          </label>
          <Input id="role" value={role} onChange={(event) => setRole(event.target.value)} />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs text-ink-dim" htmlFor="company">
            目标公司（影响面试官风格、组卷频率榜与面经追问素材）
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
          检索增强组卷（公司频率榜 × 简历押题 × 面经追问素材）
        </label>
        {error && (
          <p className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            启动失败：{error}
          </p>
        )}
        <Button className="w-full" onClick={start} disabled={busy || role.trim().length === 0}>
          {busy ? "组卷并创建会话中…" : "进入面试室"}
        </Button>
        <p className="text-center text-[11px] text-ink-faint">
          需要 apps/agents 在线（http://127.0.0.1:23481）并配置 DEEPSEEK_API_KEY
        </p>
      </CardContent>
    </Card>
  );
}
