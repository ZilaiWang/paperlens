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
    <div className="min-h-screen bg-[var(--pl-canvas)] text-[var(--pl-ink)] md:grid md:grid-cols-[212px_minmax(0,1fr)]">
      <aside className="hidden h-screen border-r border-[var(--pl-line)] bg-[var(--pl-sidebar)] px-3 py-4 md:sticky md:top-0 md:flex md:flex-col">
        <Link href="/" className="mb-7 flex items-center gap-2.5 px-2">
          <span className="grid size-7 place-items-center rounded-[9px] bg-[var(--pl-clay)] text-[13px] font-semibold text-white shadow-[0_1px_2px_rgba(50,30,20,.16)]">
            P
          </span>
          <span className="text-[15px] font-semibold tracking-[-0.02em]">PaperLens</span>
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

        <p className="mt-auto px-2 pb-1 text-[10px] leading-4 text-[var(--pl-faint)]">本地优先 · 工作区隔离</p>
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
