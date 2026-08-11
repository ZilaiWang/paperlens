"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const items = [
  { href: "/", label: "开始", icon: "⌁" },
  { href: "/library", label: "论文库", icon: "▱" },
  { href: "/compare", label: "多篇对比", icon: "⇄" },
];

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  if (href === "/library") return pathname.startsWith("/library");
  return pathname.startsWith(href);
}

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  if (pathname.startsWith("/paper/")) return children;

  return (
    <div className="min-h-screen bg-[var(--pl-canvas)] text-[var(--pl-ink)] md:grid md:grid-cols-[232px_minmax(0,1fr)]">
      <aside className="hidden h-screen border-r border-[var(--pl-line)] bg-[var(--pl-sidebar)] px-3 py-4 md:sticky md:top-0 md:flex md:flex-col">
        <Link href="/" className="mb-7 flex items-center gap-2.5 px-2">
          <span className="grid size-7 place-items-center rounded-[9px] bg-[var(--pl-clay)] text-[13px] font-semibold text-white shadow-[0_1px_2px_rgba(50,30,20,.16)]">
            P
          </span>
          <span className="text-[15px] font-semibold tracking-[-0.02em]">PaperLens</span>
          <span className="ml-auto rounded border border-[var(--pl-line-strong)] px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--pl-muted)]">
            beta
          </span>
        </Link>

        <nav className="space-y-1" aria-label="主导航">
          {items.map((item) => {
            const active = isActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`group flex h-9 items-center gap-3 rounded-lg px-2.5 text-[13px] transition-colors ${
                  active
                    ? "bg-white/75 font-medium text-[var(--pl-ink)] shadow-[0_1px_2px_rgba(38,34,28,.06)]"
                    : "text-[var(--pl-muted)] hover:bg-white/45 hover:text-[var(--pl-ink)]"
                }`}
              >
                <span className={`w-5 text-center font-mono text-[12px] ${active ? "text-[var(--pl-clay)]" : "text-[var(--pl-faint)] group-hover:text-[var(--pl-muted)]"}`}>
                  {item.icon}
                </span>
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto space-y-2">
          <Link
            href="/terms"
            aria-current={pathname.startsWith("/terms") ? "page" : undefined}
            className={`flex h-9 items-center gap-3 rounded-lg px-2.5 text-[12px] transition-colors ${
              pathname.startsWith("/terms")
                ? "bg-white/70 text-[var(--pl-ink)]"
                : "text-[var(--pl-muted)] hover:bg-white/45 hover:text-[var(--pl-ink)]"
            }`}
          >
            <span className="w-5 text-center font-mono text-[11px] text-[var(--pl-faint)]">⚙</span>
            翻译设置与词库
          </Link>
          <div className="rounded-xl border border-[var(--pl-line)] bg-white/35 p-3">
          <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.1em] text-[var(--pl-muted)]">
            <span className="size-1.5 rounded-full bg-[#6d9a73] shadow-[0_0_0_3px_rgba(109,154,115,.12)]" />
            Local workspace
          </div>
          <p className="mt-2 text-[11px] leading-4 text-[var(--pl-faint)]">
            数据保存在本机，并按工作区隔离。
          </p>
          </div>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-30 flex h-12 items-center border-b border-[var(--pl-line)] bg-[color:var(--pl-canvas)/.9] px-4 backdrop-blur md:hidden">
          <Link href="/" className="font-semibold">PaperLens</Link>
          <nav className="ml-auto flex gap-1">
            {items.slice(1).map((item) => (
              <Link key={item.href} href={item.href} className="rounded-md px-2 py-1 text-xs text-[var(--pl-muted)]">
                {item.label}
              </Link>
            ))}
          </nav>
        </header>
        {children}
      </div>
    </div>
  );
}
