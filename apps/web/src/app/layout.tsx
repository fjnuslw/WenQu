import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "问渠 WenQu — 大模型应用/Agent 求职备战平台",
  description: "面经知识库 · 厂商题库 · AI 考官模拟面试 · 项目读码拷打。问渠那得清如许，为有源头活水来。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-dvh bg-canvas text-ink antialiased">{children}</body>
    </html>
  );
}
