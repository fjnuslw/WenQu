import { InterviewStartForm } from "@/components/interview/start-form";
import { RecentInterviews } from "@/components/interview/recent-interviews";
import { PageHeader } from "@/components/page-header";

export default function InterviewPage() {
  return (
    <div className="mx-auto max-w-5xl p-8">
      <PageHeader
        title="模拟面试"
        description="证据化组卷（简历经历/项目深挖 × 公司高频题 × 面经追问）+ 七阶段状态机 + 评分报告与失分点回流。"
      />
      <InterviewStartForm />
      <RecentInterviews />
    </div>
  );
}
