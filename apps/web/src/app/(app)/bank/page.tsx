import { Suspense } from "react";

import { PageHeader } from "@/components/page-header";
import { QuestionsExplorer } from "@/components/bank/questions-explorer";

export default function BankPage() {
  return (
    <div className="mx-auto max-w-5xl p-8">
      <PageHeader
        title="题库"
        description="大模型版 CodeTop：公司 × 岗位 × 题目 × 频率。支持 /bank?tag=X 深链直达，筛选与自测模式在 K1 完整点亮。"
      />
      {/* QuestionsExplorer 用 useSearchParams 读取深链参数，静态渲染需要 Suspense 边界 */}
      <Suspense fallback={<div className="h-24 animate-pulse rounded-xl bg-surface-2/60" />}>
        <QuestionsExplorer />
      </Suspense>
    </div>
  );
}
