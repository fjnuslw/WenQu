"use client";

import { Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ResumeListItem {
  id: number;
  file_name: string;
  candidate_name: string | null;
  role_target: string | null;
  tech_stack: string[];
  highlights: string[];
}

interface JdMatchResult {
  match_score: number;
  matched: string[];
  gaps: string[];
  advantages: string[];
  suggestions: string[];
}

interface ResumeProfile {
  candidate_name?: string | null;
  role_target?: string | null;
  tech_stack?: string[];
  projects?: { name: string; points: string[]; stack?: string[] }[];
  highlights?: string[];
  exam_tags?: string[];
}

const SHOWCASE_RESUME_FILE = "README_SHOWCASE_SYNTHETIC_RESUME.pdf";

export default function ResumePage() {
  const [resumes, setResumes] = useState<ResumeListItem[] | null>(null);
  const [showcaseMode, setShowcaseMode] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [profile, setProfile] = useState<ResumeProfile | null>(null);
  const [uploading, setUploading] = useState(false);
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jdText, setJdText] = useState("");
  const [jdMatch, setJdMatch] = useState<JdMatchResult | null>(null);
  const [jdBusy, setJdBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadList = useCallback(async () => {
    try {
      const data = await apiFetch<{ items: ResumeListItem[] }>("/api/resumes");
      const showcase =
        typeof window !== "undefined" &&
        new URLSearchParams(window.location.search).get("showcase") === "1";
      const visibleItems = showcase
        ? data.items.filter((item) => item.file_name === SHOWCASE_RESUME_FILE)
        : data.items;
      setShowcaseMode(showcase);
      setResumes(visibleItems);
      setSelectedId((current) =>
        current !== null && visibleItems.some((item) => item.id === current)
          ? current
          : (visibleItems[0]?.id ?? null),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    if (selectedId === null) {
      setProfile(null);
      return;
    }
    void (async () => {
      setLoadingProfile(true);
      try {
        const data = await apiFetch<{ profile: ResumeProfile }>(`/api/resumes/${selectedId}`);
        setProfile(data.profile);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setLoadingProfile(false);
      }
    })();
  }, [selectedId]);

  async function upload(file: File) {
    setUploading(true);
    setError(null);
    try {
      // FormData：不手动设 Content-Type（浏览器需自动带 multipart boundary）
      const form = new FormData();
      form.append("file", file);
      const response = await fetch("/api/resumes/upload", { method: "POST", body: form });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
        throw new Error(body?.error?.message ?? `上传失败: ${response.status}`);
      }
      const data = (await response.json()) as { id: number };
      await loadList();
      setSelectedId(data.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function runJdMatch() {
    if (selectedId === null || jdText.trim().length < 20) {
      setError("先选择简历，并粘贴至少 20 字的 JD 原文");
      return;
    }
    setJdBusy(true);
    setError(null);
    try {
      const data = await apiFetch<JdMatchResult>(`/api/resumes/${selectedId}/jd-match`, {
        method: "POST",
        body: JSON.stringify({ jd_text: jdText.trim() }),
      });
      setJdMatch(data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setJdBusy(false);
    }
  }

  async function remove(id: number) {
    setError(null);
    try {
      await apiFetch(`/api/resumes/${id}`, { method: "DELETE" });
      await loadList();
      if (selectedId === id) {
        setSelectedId(null);
        setProfile(null);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  return (
    <div className="mx-auto max-w-4xl p-8">
      <PageHeader
        title="简历工作台"
        description="上传简历 → 结构化画像（实习/工作经历、项目、技术栈、考点标签）→ 模拟面试按原始声明深挖；项目要点同时是项目拷打的声明底稿。替换简历 = 删除旧版后重新上传。文件只存本地 data/uploads（已 gitignore，不会进 GitHub）。"
      />

      {showcaseMode && (
        <div className="mb-5 rounded-lg border border-accent/35 bg-accent-soft px-4 py-3 text-sm text-accent">
          README 安全演示模式：本页只展示仓库内生成的合成简历，不读取或显示真实候选人信息。
        </div>
      )}

      <Card className="mb-5">
        <CardContent className="flex flex-col items-start gap-3 p-5">
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf,.pdf"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void upload(file);
            }}
          />
          <Button onClick={() => fileInputRef.current?.click()} disabled={uploading}>
            <Upload className={uploading ? "size-4 animate-pulse" : "size-4"} />
            {uploading ? "解析中（约 20-40s）…" : "上传简历 PDF"}
          </Button>
          <p className="text-xs text-ink-faint">
            仅支持 PDF（≤10MB）。解析经 LLM 结构化：同一份简历的迭代版本会作为新记录并存。
          </p>
          {error && <p className="text-sm text-danger">出错了：{error}</p>}
        </CardContent>
      </Card>

      {resumes && resumes.length > 0 && (
        <div className="mb-5 flex flex-wrap gap-2">
          {resumes.map((resume) => (
            <span
              key={resume.id}
              className={
                selectedId === resume.id
                  ? "inline-flex items-center gap-1 rounded-full border border-accent/60 bg-accent-soft px-3.5 py-1.5 text-xs font-medium text-accent"
                  : "inline-flex items-center gap-1 rounded-full border border-line bg-surface-2 px-3.5 py-1.5 text-xs text-ink-dim"
              }
            >
              <button className="hover:text-ink" onClick={() => setSelectedId(resume.id)}>
                {resume.candidate_name ? `${resume.candidate_name} · ` : ""}
                {resume.file_name}
              </button>
              <button
                className="ml-0.5 rounded-full px-1 text-ink-faint transition-colors hover:bg-danger/15 hover:text-danger"
                title="删除这份简历（替换请删除后重新上传）"
                onClick={() => void remove(resume.id)}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      {loadingProfile && <p className="text-sm text-ink-dim">加载画像…</p>}

      <Card className="mb-5">
        <CardContent className="space-y-3 p-5">
          <h3 className="text-sm font-semibold text-ink">JD 匹配度</h3>
          <textarea
            className="min-h-24 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
            placeholder="粘贴目标岗位 JD 原文（岗位职责与任职要求）…"
            value={jdText}
            onChange={(event) => setJdText(event.target.value)}
          />
          <div className="flex items-center gap-3">
            <Button size="sm" onClick={() => void runJdMatch()} disabled={jdBusy || !profile}>
              {jdBusy ? "分析中…" : "评估匹配度"}
            </Button>
            <span className="text-xs text-ink-faint">需要先上传并解析简历</span>
          </div>
          {jdMatch && (
            <div className="space-y-3 rounded-lg bg-surface-2 p-4">
              <div className="flex items-baseline gap-3">
                <span className="text-2xl font-semibold text-accent">{jdMatch.match_score}</span>
                <span className="text-xs text-ink-dim">/100 匹配度</span>
              </div>
              {(
                [
                  { label: "已覆盖", items: jdMatch.matched, color: "text-ok" },
                  { label: "缺口", items: jdMatch.gaps, color: "text-warn" },
                  { label: "加分项", items: jdMatch.advantages, color: "text-accent" },
                ] as const
              ).map(
                (group) =>
                  group.items.length > 0 && (
                    <div key={group.label}>
                      <div className={`mb-1 text-xs font-medium ${group.color}`}>{group.label}</div>
                      <ul className="list-disc space-y-0.5 pl-5 text-xs leading-relaxed text-ink-dim">
                        {group.items.map((item, index) => (
                          <li key={index}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ),
              )}
              {jdMatch.suggestions.length > 0 && (
                <div>
                  <div className="mb-1 text-xs font-medium text-ink">建议</div>
                  <ul className="list-disc space-y-0.5 pl-5 text-xs leading-relaxed text-ink-dim">
                    {jdMatch.suggestions.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {profile && (
        <div className="space-y-4">
          <Card>
            <CardContent className="p-5">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <span className="text-base font-semibold text-ink">
                  {profile.candidate_name || "未命名"}
                </span>
                {profile.role_target && <Badge variant="accent">{profile.role_target}</Badge>}
              </div>
              {(profile.tech_stack ?? []).length > 0 && (
                <div className="mb-3 flex flex-wrap gap-1.5">
                  {profile.tech_stack?.map((stack) => (
                    <Badge key={stack}>{stack}</Badge>
                  ))}
                </div>
              )}
              {(profile.exam_tags ?? []).length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-xs text-ink-faint">考点标签：</span>
                  {profile.exam_tags?.map((tag) => (
                    <Badge key={tag} variant="accent">
                      {tag}
                    </Badge>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {(profile.highlights ?? []).length > 0 && (
            <Card>
              <CardContent className="p-5">
                <h3 className="mb-2.5 text-sm font-semibold text-ink">面试官会深挖的点</h3>
                <ul className="list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-ink-dim">
                  {profile.highlights?.map((highlight, index) => (
                    <li key={index}>{highlight}</li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {(profile.projects ?? []).length > 0 && (
            <Card>
              <CardContent className="p-5">
                <h3 className="mb-2.5 text-sm font-semibold text-ink">
                  项目（要点已作为「声明」入档，供项目拷打对照代码取证）
                </h3>
                <div className="space-y-4">
                  {profile.projects?.map((project) => (
                    <div key={project.name}>
                      <p className="text-sm font-medium text-ink">{project.name}</p>
                      <ul className="mt-1 list-disc space-y-1 pl-5 text-xs leading-relaxed text-ink-dim">
                        {project.points.map((point, index) => (
                          <li key={index}>{point}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {resumes && resumes.length === 0 && !uploading && (
        <Card>
          <CardContent className="p-8 text-center text-sm text-ink-dim">
            还没有简历。上传后即可在「模拟面试」按真实经历和项目进行证据化深挖。
          </CardContent>
        </Card>
      )}
    </div>
  );
}
