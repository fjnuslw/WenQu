"use client";

import { ExternalLink, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

interface ExperienceItemOut {
  id: number;
  parent_id: number | null;
  order_no: number;
  question_text: string;
  note: string | null;
}

interface ExperienceOut {
  id: number;
  company: string | null;
  role: string | null;
  round: string | null;
  occurred_on: string | null;
  result: string | null;
  url: string | null;
  items: ExperienceItemOut[];
}

interface ExperienceList {
  total: number;
  items: ExperienceOut[];
}

function QuestionTree({ items }: { items: ExperienceItemOut[] }) {
  const roots = items.filter((item) => item.parent_id === null);
  return (
    <ol className="space-y-2.5">
      {roots.map((item) => {
        const followups = items.filter((child) => child.parent_id === item.id);
        return (
          <li key={item.id} className="text-sm leading-relaxed text-ink">
            <span className="mr-1.5 text-ink-faint">{item.order_no + 1}.</span>
            {item.question_text}
            {item.note && <span className="ml-1.5 text-xs text-ink-dim">（{item.note}）</span>}
            {followups.length > 0 && (
              <ul className="mt-1.5 space-y-1 border-l-2 border-line pl-3">
                {followups.map((followup) => (
                  <li key={followup.id} className="text-xs text-ink-dim">
                    ↳ {followup.question_text}
                  </li>
                ))}
              </ul>
            )}
          </li>
        );
      })}
    </ol>
  );
}

export default function ExperiencesPage() {
  const [data, setData] = useState<ExperienceList | null>(null);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setFetching(true);
    setError(null);
    try {
      const result = await apiFetch<ExperienceList>("/api/experiences?limit=50");
      setData(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setFetching(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto max-w-5xl p-8">
      <PageHeader
        title="面经"
        description="结构化面经流（公司-岗位-轮次-问题树），由牛客话题页等公开渠道采集 + LLM 结构化抽取。"
      />

      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-ink-dim">{data ? `共 ${data.total} 条面经` : "加载中…"}</p>
        <Button variant="secondary" size="sm" onClick={() => void load()} disabled={fetching}>
          <RefreshCw className={fetching ? "size-4 animate-spin" : "size-4"} />
          刷新
        </Button>
      </div>

      {error && <p className="mb-4 text-sm text-danger">出错了：{error}</p>}

      {data && data.items.length === 0 && (
        <Card>
          <CardContent className="p-8 text-center text-sm text-ink-dim">
            题库还没有面经。采集入口：
            <code className="mx-1 rounded bg-surface-2 px-1.5 py-0.5 text-xs">
              POST /api/ingest/collect/nowcoder
            </code>
          </CardContent>
        </Card>
      )}

      <div className={fetching ? "space-y-4 opacity-60 transition-opacity" : "space-y-4"}>
        {data?.items.map((experience) => (
          <Card key={experience.id}>
            <CardContent className="p-5">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {experience.company ? (
                  <Badge variant="accent">{experience.company}</Badge>
                ) : (
                  <Badge>公司未识别</Badge>
                )}
                {experience.role && <Badge>{experience.role}</Badge>}
                {experience.round && <Badge>{experience.round}</Badge>}
                {experience.result && experience.result !== "未知" && (
                  <Badge variant={experience.result === "通过" ? "ok" : "warn"}>
                    {experience.result}
                  </Badge>
                )}
                {experience.occurred_on && (
                  <span className="text-xs text-ink-faint">{experience.occurred_on}</span>
                )}
                {experience.url && (
                  <a
                    className="ml-auto inline-flex items-center gap-1 text-xs text-accent hover:underline"
                    href={experience.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    原帖
                    <ExternalLink className="size-3" />
                  </a>
                )}
              </div>
              <QuestionTree items={experience.items} />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
