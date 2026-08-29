"use client";

import { Search, Swords, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { agentsUrl, apiFetch } from "@/lib/api";

interface ModuleBriefing {
  files: string[];
  purpose: string;
  tech_points: string[];
  detail_questions: string[];
  alternative_question?: string | null;
  missing_question?: string | null;
}

interface GrillPrep {
  project_id: number;
  name: string;
  repo_root: string;
  resume_used: boolean;
  file_count: number;
  language_mix: Record<string, number>;
  briefing: { overview: string; stack_summary: string; modules: ModuleBriefing[] };
  claim_checks: { claim: string; status: string; evidence?: string | null; probe_question: string }[];
}

interface ResumeListItem {
  id: number;
  file_name: string;
  candidate_name: string | null;
}

const STATUS_BADGE: Record<string, { label: string; variant: "ok" | "warn" | "danger" }> = {
  supported: { label: "有据", variant: "ok" },
  suspicious: { label: "存疑", variant: "warn" },
  not_found: { label: "无痕迹", variant: "danger" },
};

export default function GrillingPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [resumes, setResumes] = useState<ResumeListItem[]>([]);
  const [resumeId, setResumeId] = useState<number | null>(null);
  const [prepping, setPrepping] = useState(false);
  const [prep, setPrep] = useState<GrillPrep | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void apiFetch<{ items: ResumeListItem[] }>("/api/resumes")
      .then((data) => {
        setResumes(data.items);
        if (data.items.length > 0) setResumeId(data.items[0].id);
      })
      .catch(() => setResumes([]));
  }, []);

  async function prepare(file: File) {
    if (!name.trim()) {
      setError("先给项目起个名字（如 local-copilot）");
      return;
    }
    setPrepping(true);
    setError(null);
    setPrep(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("name", name.trim());
      if (resumeId !== null) form.append("resume_id", String(resumeId));
      const response = await fetch("/api/grill/projects", { method: "POST", body: form });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
        throw new Error(body?.error?.message ?? `备课失败: ${response.status}`);
      }
      setPrep((await response.json()) as GrillPrep);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setPrepping(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function startGrill() {
    if (!prep) return;
    setStarting(true);
    setError(null);
    try {
      const response = await fetch(agentsUrl("/sessions"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "grill",
          persona: { role: "大模型应用/Agent 开发" },
          maxQuestionsPerPhase: 6,
          maxFollowUpDepth: 4,
          grill: {
            projectId: prep.project_id,
            projectName: prep.name,
            repoRoot: prep.repo_root,
            briefing: prep.briefing,
            claimChecks: prep.claim_checks,
          },
        }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
        throw new Error(body?.error?.message ?? `创建拷打会话失败: ${response.status}`);
      }
      const { id } = (await response.json()) as { id: string };
      router.push(`/interview/${id}?mode=grill`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl p-8">
      <PageHeader
        title="项目拷打"
        description="上传项目源码 zip → AI 备课（模块/考点/拷打题 + 简历声明对照）→ 拷打官对照真实代码逐层深挖：怎么实现的、为什么不用别的方案、为什么没做。"
      />

      <Card className="mb-5">
        <CardContent className="space-y-4 p-5">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-xs text-ink-dim" htmlFor="project-name">
                项目名
              </label>
              <Input
                id="project-name"
                placeholder="如 local-copilot"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-ink-dim" htmlFor="grill-resume">
                对照简历（可选，做声明质证）
              </label>
              <select
                id="grill-resume"
                value={resumeId ?? ""}
                onChange={(event) => setResumeId(event.target.value ? Number(event.target.value) : null)}
                className="h-9 w-full rounded-md border border-line bg-surface px-3 text-sm text-ink focus:border-accent focus:outline-none"
              >
                <option value="">不对照简历</option>
                {resumes.map((resume) => (
                  <option key={resume.id} value={resume.id}>
                    {resume.candidate_name ? `${resume.candidate_name} · ` : ""}
                    {resume.file_name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/zip,.zip"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void prepare(file);
            }}
          />
          <div className="flex items-center gap-3">
            <Button onClick={() => fileInputRef.current?.click()} disabled={prepping || !name.trim()}>
              <Upload className={prepping ? "size-4 animate-pulse" : "size-4"} />
              {prepping ? "备课中（1-3 分钟，读码+生成拷打题）…" : "上传项目 zip 开始备课"}
            </Button>
            <span className="text-[11px] text-ink-faint">
              zip ≤50MB；node_modules/.git 等自动过滤。同一项目名不能重复备课。
            </span>
          </div>
          {error && <p className="text-sm text-danger">出错了：{error}</p>}
        </CardContent>
      </Card>

      {prep && (
        <div className="space-y-4">
          <Card>
            <CardContent className="p-5">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <span className="text-base font-semibold text-ink">{prep.name}</span>
                <Badge variant="accent">{prep.file_count} 个文件</Badge>
                {prep.resume_used && <Badge>已对照简历</Badge>}
                <Button className="ml-auto" onClick={() => void startGrill()} disabled={starting}>
                  <Swords className={starting ? "size-4 animate-pulse" : "size-4"} />
                  {starting ? "创建拷打会话…" : "开始拷打"}
                </Button>
              </div>
              <p className="text-sm leading-relaxed text-ink">{prep.briefing.overview}</p>
              <p className="mt-2 text-xs text-ink-dim">{prep.briefing.stack_summary}</p>
            </CardContent>
          </Card>

          {prep.claim_checks.length > 0 && (
            <Card>
              <CardContent className="p-5">
                <h3 className="mb-2.5 flex items-center gap-2 text-sm font-semibold text-ink">
                  <Search className="size-4" />
                  简历声明对照（拷打官的质证清单）
                </h3>
                <ul className="space-y-2">
                  {prep.claim_checks.map((check, index) => {
                    const badge = STATUS_BADGE[check.status] ?? STATUS_BADGE.supported;
                    return (
                      <li key={index} className="text-xs leading-relaxed">
                        <Badge variant={badge.variant} className="mr-1.5">
                          {badge.label}
                        </Badge>
                        <span className="text-ink">{check.claim}</span>
                        <span className="mt-0.5 block text-ink-dim">质证：{check.probe_question}</span>
                      </li>
                    );
                  })}
                </ul>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardContent className="p-5">
              <h3 className="mb-2.5 text-sm font-semibold text-ink">模块与拷打弹药（备课产物）</h3>
              <div className="space-y-3">
                {prep.briefing.modules.map((module, index) => (
                  <div key={index} className="rounded-lg bg-surface-2 p-3">
                    <p className="text-sm font-medium text-ink">{module.purpose}</p>
                    <p className="mt-0.5 font-mono text-[11px] text-ink-faint">
                      {module.files.slice(0, 4).join(" · ")}
                    </p>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {module.tech_points.map((point) => (
                        <Badge key={point}>{point}</Badge>
                      ))}
                    </div>
                    <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-ink-dim">
                      {module.detail_questions.slice(0, 3).map((question, qIndex) => (
                        <li key={qIndex}>{question}</li>
                      ))}
                      {module.alternative_question && <li>{module.alternative_question}</li>}
                      {module.missing_question && <li>{module.missing_question}</li>}
                    </ul>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
