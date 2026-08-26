import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI 留学申请分析",
  description: "AI 留学申请分析 MVP",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
