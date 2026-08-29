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

interface ResumeProfile {
  candidate_name?: string | null;
  role_target?: string | null;
  tech_stack?: string[];
  projects?: { name: string; points: string[]; stack?: string[] }[];
  highlights?: string[];
  exam_tags?: string[];
}

export default function ResumePage() {
  const [resumes, setResumes] = useState<ResumeListItem[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [profile, setProfile] = useState<ResumeProfile | null>(null);
  const [uploading, setUploading] = useState(false);
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadList = useCallback(async () => {
    try {
      const data = await apiFetch<{ items: ResumeListItem[] }>("/api/resumes");
      setResumes(data.items);
      setSelectedId((current) => current ?? data.items[0]?.id ?? null);
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

  return (
    <div className="mx-auto max-w-4xl p-8">
      <PageHeader
        title="简历工作台"
        description="上传简历 → 结构化画像（技术栈/项目要点/考点标签）→ 模拟面试按简历押题；项目要点同时是项目拷打的声明底稿。"
      />

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
          <p className="text-[11px] text-ink-faint">
            仅支持 PDF（≤10MB）。解析经 LLM 结构化：同一份简历的迭代版本会作为新记录并存。
          </p>
          {error && <p className="text-sm text-danger">出错了：{error}</p>}
        </CardContent>
      </Card>

      {resumes && resumes.length > 0 && (
        <div className="mb-5 flex flex-wrap gap-2">
          {resumes.map((resume) => (
            <button
              key={resume.id}
              className={cn(
                "rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors",
                selectedId === resume.id
                  ? "border-accent/60 bg-accent-soft text-accent"
                  : "border-line bg-surface-2 text-ink-dim hover:border-line-strong hover:text-ink",
              )}
              onClick={() => setSelectedId(resume.id)}
            >
              {resume.candidate_name ? `${resume.candidate_name} · ` : ""}
              {resume.file_name}
            </button>
          ))}
        </div>
      )}

      {loadingProfile && <p className="text-sm text-ink-dim">加载画像…</p>}

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
                  <span className="text-[11px] text-ink-faint">考点标签：</span>
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
            还没有简历。上传后即可在「模拟面试」按简历押题组卷。
          </CardContent>
        </Card>
      )}
    </div>
  );
}
