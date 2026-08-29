import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";

export default function GrillingPage() {
  return (
    <div className="mx-auto max-w-5xl p-8">
      <PageHeader
        title="项目拷打"
        description="核心差异化：上传完整 Git 仓库 + 简历，AI 读码后基于真实代码证据深挖拷打。"
      />
      <Card>
        <CardHeader>
          <CardTitle>交付状态</CardTitle>
          <Badge variant="accent">G1</Badge>
        </CardHeader>
        <CardContent className="space-y-2">
          <p>
            备课流水线（repomap PageRank 考点权重 / cAST 分块 / wiki / git 归属）与只读工具面在
            <strong className="text-ink"> G1 里程碑 </strong>
            点亮；后端内部端点契约见 spec §5.1，本页显式占位而非假实现。
          </p>
          <ul className="list-disc space-y-1 pl-5 text-ink-dim">
            <li>输入：Git 仓库（本地路径 / GitHub URL）+ 简历声明</li>
            <li>输出：注水疑点清单 → 拷打对话 → 证据链评分报告（文件:行号）</li>
            <li>首个测试用例：research/04 §5（本简历 × OpenSOP / Local Window Copilot）</li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
