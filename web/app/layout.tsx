import type { Metadata } from "next";
import "./globals.css";
// V3.21 公式排版：KaTeX 样式（app router 全局 CSS 只能进根布局）
import "katex/dist/katex.min.css";

export const metadata: Metadata = {
  title: "PaperLens",
  description: "面向计算机视觉论文的双语、证据可追溯阅读工作台",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
