import { InterviewStartForm } from "@/components/interview/start-form";
import { PageHeader } from "@/components/page-header";

export default function InterviewPage() {
  return (
    <div className="mx-auto max-w-5xl p-8">
      <PageHeader
        title="模拟面试"
        description="AI 考官：七阶段状态机 + 4 级提示降级追问链，模型 DeepSeek-V4-Flash-Vision-Exp。评分报告在 I1 里程碑点亮。"
      />
      <InterviewStartForm />
    </div>
  );
}
