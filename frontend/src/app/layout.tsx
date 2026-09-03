import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Viaform｜结构化申请规划",
  description: "从申请背景与目标项目要求出发，生成结构化 Gap Analysis 与申请行动计划。",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
