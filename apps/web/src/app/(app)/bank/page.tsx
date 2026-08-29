import { PageHeader } from "@/components/page-header";
import { QuestionsExplorer } from "@/components/bank/questions-explorer";

export default function BankPage() {
  return (
    <div className="mx-auto max-w-5xl p-8">
      <PageHeader
        title="题库"
        description="大模型版 CodeTop：公司 × 岗位 × 题目 × 频率。筛选与自测模式在 K1 完整点亮。"
      />
      <QuestionsExplorer />
    </div>
  );
}
