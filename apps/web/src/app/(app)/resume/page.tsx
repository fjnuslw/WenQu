import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";

export default function ResumePage() {
  return (
    <div className="mx-auto max-w-5xl p-8">
      <PageHeader
        title="简历工作台"
        description="JD 匹配度 · 简历押题 · 简历-题库联动 · 量化口径检测。"
      />
      <Card>
        <CardHeader>
          <CardTitle>交付状态</CardTitle>
          <Badge variant="accent">L1</Badge>
        </CardHeader>
        <CardContent>
          <p>
            简历解析器（pypdf → 声明抽取）在 I1 与 F3 共享点亮；工作台 UI 与 JD 对比视图在 L1 交付。
            简历画像与考点映射金标准已就绪：research/04。
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
