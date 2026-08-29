"use client";

import { ExternalLink, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { CompanyLogo } from "@/components/company-logo";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/utils";

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
  company_logo: string | null;
  source_slug: string | null;
  source_name: string | null;
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

const COLLAPSED_QUESTIONS = 3;

function QuestionTree({ items }: { items: ExperienceItemOut[] }) {
  const roots = items.filter((item) => item.parent_id === null);
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? roots : roots.slice(0, COLLAPSED_QUESTIONS);
  if (roots.length === 0) return null;

  return (
    <div>
      <ol className="space-y-2.5">
        {visible.map((item) => {
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
      {roots.length > COLLAPSED_QUESTIONS && (
        <button
          className="mt-2.5 text-xs text-accent hover:underline"
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "收起" : `展开全部 ${roots.length} 题`}
        </button>
      )}
    </div>
  );
}

/** 来源 tab：数据驱动（渠道注册表落到 sources 表后自动出现新 tab）。 */
function SourceTabs({
  sources,
  active,
  onChange,
}: {
  sources: { slug: string; name: string; count: number }[];
  active: string | null;
  onChange: (slug: string | null) => void;
}) {
  const total = sources.reduce((sum, source) => sum + source.count, 0);
  const tabs = [{ slug: null, name: "全部", count: total }, ...sources];
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {tabs.map((tab) => (
        <button
          key={tab.slug ?? "all"}
          className={cn(
            "rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors",
            active === tab.slug
              ? "border-accent/60 bg-accent-soft text-accent"
              : "border-line bg-surface-2 text-ink-dim hover:border-line-strong hover:text-ink",
          )}
          onClick={() => onChange(tab.slug)}
        >
          {tab.name}
          <span className="ml-1.5 text-ink-faint">{tab.count}</span>
        </button>
      ))}
    </div>
  );
}

function CompanyChips({
  companies,
  active,
  onChange,
}: {
  companies: { name: string; logo: string | null; count: number }[];
  active: string | null;
  onChange: (name: string | null) => void;
}) {
  if (companies.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        className={cn(
          "rounded-full border px-3 py-1 text-xs transition-colors",
          active === null
            ? "border-accent/60 bg-accent-soft text-accent"
            : "border-line bg-surface-2 text-ink-dim hover:text-ink",
        )}
        onClick={() => onChange(null)}
      >
        不限公司
      </button>
      {companies.map((company) => (
        <button
          key={company.name}
          className={cn(
            "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors",
            active === company.name
              ? "border-accent/60 bg-accent-soft text-accent"
              : "border-line bg-surface-2 text-ink-dim hover:text-ink",
          )}
          onClick={() => onChange(active === company.name ? null : company.name)}
        >
          <CompanyLogo name={company.name} logo={company.logo} size="xs" />
          {company.name}
          <span className="text-ink-faint">{company.count}</span>
        </button>
      ))}
    </div>
  );
}

export default function ExperiencesPage() {
  const [data, setData] = useState<ExperienceList | null>(null);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceSlug, setSourceSlug] = useState<string | null>(null);
  const [company, setCompany] = useState<string | null>(null);

  const load = useCallback(async () => {
    setFetching(true);
    setError(null);
    try {
      const result = await apiFetch<ExperienceList>("/api/experiences?limit=100");
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

  // 来源分组（按数量降序）；公司分组随来源过滤联动
  const sources = useMemo(() => {
    const counts = new Map<string, { slug: string; name: string; count: number }>();
    for (const item of data?.items ?? []) {
      const slug = item.source_slug ?? "unknown";
      const entry = counts.get(slug) ?? { slug, name: item.source_name ?? "未知来源", count: 0 };
      entry.count += 1;
      counts.set(slug, entry);
    }
    return [...counts.values()].sort((a, b) => b.count - a.count);
  }, [data]);

  const companies = useMemo(() => {
    const counts = new Map<string, { name: string; logo: string | null; count: number }>();
    for (const item of data?.items ?? []) {
      if (sourceSlug !== null && item.source_slug !== sourceSlug) continue;
      if (!item.company) continue;
      const entry = counts.get(item.company) ?? {
        name: item.company,
        logo: item.company_logo,
        count: 0,
      };
      entry.count += 1;
      counts.set(item.company, entry);
    }
    return [...counts.values()].sort((a, b) => b.count - a.count);
  }, [data, sourceSlug]);

  const filtered = useMemo(() => {
    return (data?.items ?? []).filter(
      (item) =>
        (sourceSlug === null || item.source_slug === sourceSlug) &&
        (company === null || item.company === company),
    );
  }, [data, sourceSlug, company]);

  return (
    <div className="mx-auto max-w-5xl p-8">
      <PageHeader
        title="面经"
        description="结构化面经流（公司-岗位-轮次-问题树），由公开渠道采集 + LLM 结构化抽取，点击原帖可溯源。"
      />

      <div className="mb-5 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm text-ink-dim">
            {data ? `${filtered.length}/${data.total} 条面经` : "加载中…"}
          </p>
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={fetching}>
            <RefreshCw className={fetching ? "size-4 animate-spin" : "size-4"} />
            刷新
          </Button>
        </div>
        {data && data.items.length > 0 && (
          <>
            <SourceTabs sources={sources} active={sourceSlug} onChange={setSourceSlug} />
            <CompanyChips
              companies={companies}
              active={company}
              onChange={(name) => setCompany(name)}
            />
          </>
        )}
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
        {filtered.map((experience) => (
          <Card key={experience.id} className="card-hover">
            <CardContent className="p-5">
              <div className="mb-3 flex flex-wrap items-center gap-2.5">
                {experience.company ? (
                  <span className="flex items-center gap-2">
                    <CompanyLogo name={experience.company} logo={experience.company_logo} size="sm" />
                    <span className="text-sm font-semibold text-ink">{experience.company}</span>
                  </span>
                ) : (
                  <span className="text-sm font-medium text-ink-dim">公司未识别</span>
                )}
                {experience.role && <Badge>{experience.role}</Badge>}
                {experience.round && <Badge variant="accent">{experience.round}</Badge>}
                {experience.result && experience.result !== "未知" && (
                  <Badge variant={experience.result === "通过" ? "ok" : "warn"}>
                    {experience.result}
                  </Badge>
                )}
                <span className="ml-auto flex items-center gap-3">
                  {experience.source_name && (
                    <span className="text-[11px] text-ink-faint">来源：{experience.source_name}</span>
                  )}
                  {experience.occurred_on && (
                    <span className="text-xs text-ink-faint">{experience.occurred_on}</span>
                  )}
                  {experience.url && (
                    <a
                      className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
                      href={experience.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      原帖
                      <ExternalLink className="size-3" />
                    </a>
                  )}
                </span>
              </div>
              <QuestionTree items={experience.items} />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
