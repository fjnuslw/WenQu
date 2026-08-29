import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";

export default function ExperiencesPage() {
  return (
    <div className="mx-auto max-w-5xl p-8">
      <PageHeader
        title="面经"
        description="结构化面经流（公司-岗位-轮次-问题树）。K1 点亮：牛客/linux.do 采集 + LLM 抽取 + RAG 问答。"
      />
      <Card>
        <CardHeader>
          <CardTitle>采集管道状态</CardTitle>
          <Badge variant="accent">K1</Badge>
        </CardHeader>
        <CardContent>
          <ul className="list-disc space-y-1 pl-5">
            <li>开源仓库导入器：已实现（apps/api/ingest，license 门禁强制）</li>
            <li>牛客话题页采集（SSR 种子 + 低频）：K1</li>
            <li>linux.do Discourse JSON API 采集：K1</li>
            <li>小红书/抖音：仅人工摘录入口（平台红线，spec §10）</li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
