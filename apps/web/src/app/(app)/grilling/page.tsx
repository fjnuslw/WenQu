"use client";

import { FolderOpen, Search, Swords, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

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

interface ProjectCard {
  id: number;
  name: string;
  status: string;
  error?: string | null;
  file_count: number;
  module_count: number;
  overview: string;
  in_projects_dir: boolean;
  created_at: string | null;
}

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

const STATUS_BADGE: Record<string, { label: string; variant: "ok" | "warn" | "danger" }> = {
  supported: { label: "有据", variant: "ok" },
  suspicious: { label: "存疑", variant: "warn" },
  not_found: { label: "无痕迹", variant: "danger" },
};

export default function GrillingPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"dir" | "zip">("dir");
  const [localPath, setLocalPath] = useState("");
  const [name, setName] = useState("");
  const [resumes, setResumes] = useState<ResumeListItem[]>([]);
  const [resumeId, setResumeId] = useState<number | null>(null);
  const [prepping, setPrepping] = useState(false);
  const [progress, setProgress] = useState<{ step: string; progress: number } | null>(null);
  const [prep, setPrep] = useState<GrillPrep | null>(null);
  const [starting, setStarting] = useState(false);
  const [projects, setProjects] = useState<ProjectCard[] | null>(null);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [expandedProject, setExpandedProject] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dirInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void apiFetch<{ items: ResumeListItem[] }>("/api/resumes")
      .then((data) => {
        setResumes(data.items);
        if (data.items.length > 0) setResumeId(data.items[0].id);
      })
      .catch(() => setResumes([]));
  }, []);

  const loadProjects = useCallback(async () => {
    try {
      const [projectList, sessionList] = await Promise.all([
        apiFetch<{ items: ProjectCard[] }>("/api/grill/projects"),
        fetch(agentsUrl("/sessions")).then(async (response) =>
          response.ok ? ((await response.json()) as { items: SessionItem[] }).items : [],
        ),
      ]).catch(() => [null, []] as const);
      if (projectList) setProjects(projectList.items);
      setSessions(
        (sessionList as SessionItem[]).filter((item) => item.mode === "grill" && item.projectName),
      );
    } catch {
      // 板块加载失败不阻塞新备课
    }
  }, []);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  async function prepareDir() {
    const trimmed = localPath.trim();
    if (!trimmed) {
      setError("先填项目目录的本地绝对路径");
      return;
    }
    setPrepping(true);
    setError(null);
    setPrep(null);
    try {
      const form = new FormData();
      form.append("local_path", trimmed);
      if (name.trim()) form.append("name", name.trim());
      if (resumeId !== null) form.append("resume_id", String(resumeId));
      const response = await fetch("/api/grill/projects", { method: "POST", body: form });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
        throw new Error(body?.error?.message ?? `备课失败: ${response.status}`);
      }
      const started = (await response.json()) as { project_id: number };
      await pollPreparation(started.project_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setPrepping(false);
    }
  }

  /** 轮询备课进度（后端分钟级异步任务；详情接口就绪前返回 status/step/progress）。 */
  async function pollPreparation(projectId: number) {
    for (let attempt = 0; attempt < 240; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 2500));
      const data = await apiFetch<
        GrillPrep & { status?: string; step?: string; progress?: number; error?: string | null }
      >(`/api/grill/projects/${projectId}`);
      if (data.status === "failed") {
        throw new Error(`备课失败：${data.error ?? "未知错误"}`);
      }
      setProgress({ step: data.step ?? "备课中", progress: data.progress ?? 0 });
      if (data.status === "ready" && data.briefing) {
        setPrep(data);
        setProgress(null);
        return;
      }
    }
    throw new Error("备课超时（10 分钟）——项目可能过大，请查看后端日志");
  }

  /** 浏览器目录选择（webkitdirectory）→ 客户端 zip（JSZip）→ zip 备课通道。
   *  浏览器安全模型拿不到绝对路径，本地 localhost 上传零成本。 */
  async function prepareDirectory(fileList: FileList) {
    const first = fileList[0];
    if (!first) return;
    const rootName = (first.webkitRelativePath || "selected-dir").split("/")[0] || "selected-dir";
    setPrepping(true);
    setError(null);
    setPrep(null);
    setProgress({ step: "浏览器打包中", progress: 2 });
    try {
      const { default: JSZip } = await import("jszip");
      const zip = new JSZip();
      const skipped = new Set([
        "node_modules", ".git", "miniprogram_npm", ".venv", "venv", "dist", "build",
        "unpackage", "uni_modules", "__pycache__", ".next",
      ]);
      for (const file of Array.from(fileList)) {
        const rel = (file.webkitRelativePath || file.name).split("/").slice(1).join("/");
        if (!rel || file.size > 512 * 1024) continue; // 大文件多为构建产物
        if (rel.split("/").slice(0, -1).some((part) => skipped.has(part))) continue;
        zip.file(rel, file);
      }
      const blob = await zip.generateAsync({ type: "blob", compression: "DEFLATE" });
      const form = new FormData();
      form.append("file", new File([blob], `${rootName}.zip`, { type: "application/zip" }));
      form.append("name", name.trim() || rootName);
      if (resumeId !== null) form.append("resume_id", String(resumeId));
      const response = await fetch("/api/grill/projects", { method: "POST", body: form });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
        throw new Error(body?.error?.message ?? `备课失败: ${response.status}`);
      }
      const started = (await response.json()) as { project_id: number };
      await pollPreparation(started.project_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setProgress(null);
    } finally {
      setPrepping(false);
      if (dirInputRef.current) dirInputRef.current.value = "";
    }
  }

  async function prepareZip(file: File) {
    setPrepping(true);
    setError(null);
    setPrep(null);
    try {
      const form = new FormData();
      form.append("file", file);
      if (name.trim()) form.append("name", name.trim());
      else {
        // zip 文件名去扩展名作项目名（服务端同样兜底，这里显式带上）
        const derived = file.name.replace(/\.zip$/i, "").replace(/[\\/.]/g, "_");
        form.append("name", derived || "uploaded-project");
      }
      if (resumeId !== null) form.append("resume_id", String(resumeId));
      const response = await fetch("/api/grill/projects", { method: "POST", body: form });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
        throw new Error(body?.error?.message ?? `备课失败: ${response.status}`);
      }
      const started = (await response.json()) as { project_id: number };
      await pollPreparation(started.project_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setProgress(null);
    } finally {
      setPrepping(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  /** 开一场拷打会话（新备课产物或已存项目均可）。 */
  async function startGrill(project: GrillPrep) {
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
            projectId: project.project_id,
            projectName: project.name,
            repoRoot: project.repo_root,
            briefing: project.briefing,
            claimChecks: project.claim_checks,
          },
        }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
        throw new Error(body?.error?.message ?? `创建拷打会话失败: ${response.status}`);
      }
      const { id } = (await response.json()) as { id: string };
      router.push(`/interview/${id}?mode=grill&project=${project.project_id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setStarting(false);
    }
  }

  /** 项目卡片上直接开打：拉详情（含 briefing）→ 建会话。 */
  async function reloadAndStart(projectId: number) {
    setError(null);
    try {
      const detail = await apiFetch<GrillPrep & { status?: string }>(`/api/grill/projects/${projectId}`);
      if (!detail.briefing) throw new Error("该项目还没有备课产物");
      await startGrill(detail);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function removeProject(id: number, name: string) {
    if (!window.confirm(`删除项目「${name}」？备课产物与历次拷打记录入口将一并移除（原目录不受影响时不动源码）。`)) return;
    setError(null);
    try {
      await apiFetch(`/api/grill/projects/${id}`, { method: "DELETE" });
      await loadProjects();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  return (
    <div className="mx-auto max-w-4xl p-8">
      <PageHeader
        title="项目拷打"
        description="本地部署形态：直接填项目目录路径（原位读码，零上传）或传 zip → AI 备课（模块/考点/拷打题 + 简历声明对照）→ 拷打官对照真实代码逐层深挖。"
      />

      <Card className="mb-5">
        <CardContent className="space-y-4 p-5">
          <div className="flex items-center gap-2">
            {(
              [
                { key: "dir", label: "本地目录（推荐）", icon: FolderOpen },
                { key: "zip", label: "zip 上传", icon: Upload },
              ] as const
            ).map((option) => (
              <button
                key={option.key}
                className={
                  mode === option.key
                    ? "flex items-center gap-1.5 rounded-full border border-accent/60 bg-accent-soft px-3.5 py-1.5 text-xs font-medium text-accent"
                    : "flex items-center gap-1.5 rounded-full border border-line bg-surface-2 px-3.5 py-1.5 text-xs text-ink-dim hover:text-ink"
                }
                onClick={() => setMode(option.key)}
              >
                <option.icon className="size-3.5" />
                {option.label}
              </button>
            ))}
          </div>

          {mode === "dir" ? (
            <div className="space-y-2.5">
              <input
                ref={dirInputRef}
                type="file"
                className="hidden"
                // @ts-expect-error 浏览器专有属性：原生目录选择对话框
                webkitdirectory=""
                directory=""
                multiple
                onChange={(event) => {
                  const files = event.target.files;
                  if (files && files.length > 0) void prepareDirectory(files);
                }}
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button onClick={() => dirInputRef.current?.click()} disabled={prepping}>
                  <FolderOpen className={prepping ? "size-4 animate-pulse" : "size-4"} />
                  {prepping ? "处理中…" : "选择项目文件夹…"}
                </Button>
                <span className="text-xs text-ink-faint">
                  系统文件管理器选目录 → 浏览器打包上传（node_modules 等自动过滤）
                </span>
              </div>
              <details className="text-xs text-ink-faint">
                <summary className="cursor-pointer select-none hover:text-ink-dim">
                  高级：粘贴服务器本地路径（原位读取，零上传）
                </summary>
                <div className="mt-2 flex gap-2">
                  <Input
                    placeholder="D:\projects\my-agent（绝对路径）"
                    value={localPath}
                    onChange={(event) => setLocalPath(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !prepping && localPath.trim()) void prepareDir();
                    }}
                  />
                  <Button variant="secondary" onClick={() => void prepareDir()} disabled={prepping || !localPath.trim()}>
                    原位备课
                  </Button>
                </div>
              </details>
            </div>
          ) : (
            <div className="space-y-1.5">
              <label className="text-xs text-ink-dim">项目源码 zip（≤50MB，node_modules 自动过滤）</label>
              <input
                ref={fileInputRef}
                type="file"
                accept="application/zip,.zip"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void prepareZip(file);
                }}
              />
              <div>
                <Button onClick={() => fileInputRef.current?.click()} disabled={prepping}>
                  <Upload className={prepping ? "size-4 animate-pulse" : "size-4"} />
                  {prepping ? "备课中…" : "选择 zip 并备课"}
                </Button>
              </div>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-xs text-ink-dim" htmlFor="project-name">
                项目名（可留空 = 目录名/zip 名）
              </label>
              <Input
                id="project-name"
                placeholder="自动推导"
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
          {prepping && (
            <div className="space-y-2 rounded-lg border border-accent/25 bg-accent-soft/40 px-3.5 py-3">
              <div className="flex items-center justify-between text-xs">
                <span className="text-ink">{progress?.step ?? "提交备课任务…"}</span>
                <span className="font-mono text-accent">{progress ? `${progress.progress}%` : "…"}</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full bg-accent transition-all duration-500"
                  style={{ width: `${Math.max(3, progress?.progress ?? 3)}%` }}
                />
              </div>
              <p className="text-xs leading-relaxed text-ink-faint">
                读码 → 分批 LLM 备课 → {resumeId !== null ? "简历声明对照 → " : ""}完成。大仓库需要几分钟，进度实时更新，可以离开本页稍后在下面列表里回来。
              </p>
            </div>
          )}
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
                <span className="font-mono text-xs text-ink-faint">{prep.repo_root}</span>
                <Button className="ml-auto" onClick={() => void startGrill(prep)} disabled={starting}>
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
                    <p className="mt-0.5 font-mono text-xs text-ink-faint">
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

      <section className="mt-8">
        <h2 className="mb-3 text-sm font-semibold text-ink">已备课项目</h2>
        {projects === null && <p className="text-xs text-ink-dim">加载中…</p>}
        {projects !== null && projects.length === 0 && (
          <p className="text-xs text-ink-faint">还没有备课过的项目——上面选个目录开始第一次备课。</p>
        )}
        <div className="space-y-3">
          {projects?.map((project) => {
            const projectSessions = sessions.filter((item) => item.projectName === project.name);
            return (
              <Card key={project.id} className="card-hover">
                <CardContent className="p-4">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <span className="text-sm font-semibold text-ink">{project.name}</span>
                    {project.status === "ready" ? (
                      <span className="text-xs text-ink-dim">
                        {project.file_count} 文件 · {project.module_count} 模块
                      </span>
                    ) : project.status === "failed" ? (
                      <span className="text-xs text-danger">备课失败：{project.error ?? "未知"}</span>
                    ) : (
                      <span className="text-xs text-warn">备课中…</span>
                    )}
                    <span className="ml-auto text-xs text-ink-faint">
                      {project.created_at ? new Date(project.created_at).toLocaleString("zh-CN") : ""}
                    </span>
                  </div>
                  {project.overview && (
                    <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-ink-dim">{project.overview}</p>
                  )}
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    {project.status === "ready" && (
                      <Button size="sm" onClick={() => void reloadAndStart(project.id)} disabled={starting}>
                        <Swords className="size-3.5" />
                        {projectSessions.length > 0 ? "再开一场" : "开始拷打"}
                      </Button>
                    )}
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setExpandedProject(expandedProject === project.id ? null : project.id)}
                    >
                      {expandedProject === project.id ? "收起拷打记录" : `拷打记录（${projectSessions.length}）`}
                    </Button>
                    <Button variant="danger" size="sm" onClick={() => void removeProject(project.id, project.name)}>
                      删除
                    </Button>
                  </div>
                  {expandedProject === project.id && (
                    <div className="mt-3 space-y-1.5 border-t border-line pt-3">
                      {projectSessions.length === 0 && (
                        <p className="text-xs text-ink-faint">这个项目还没有拷打记录。</p>
                      )}
                      {projectSessions.map((item) => (
                        <button
                          key={item.id}
                          className="flex w-full items-baseline gap-x-3 rounded-md px-2 py-1.5 text-left hover:bg-surface-2"
                          onClick={() =>
                            router.push(
                              `/interview/${item.id}?mode=grill${item.projectId !== null ? `&project=${item.projectId}` : ""}`,
                            )
                          }
                        >
                          <span className="text-xs font-medium text-ink">
                            {item.last_ts ? new Date(item.last_ts).toLocaleString("zh-CN") : "—"}
                          </span>
                          <span className="text-xs text-ink-dim">{item.turns} 轮</span>
                          <span className={`ml-auto text-xs ${item.alive ? "text-ok" : "text-ink-faint"}`}>
                            {item.alive ? "可继续" : "仅回放"}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>
    </div>
  );
}
