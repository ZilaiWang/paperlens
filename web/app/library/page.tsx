"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, type PaperRow } from "@/lib/api";

export default function LibraryPage() {
  const [papers, setPapers] = useState<PaperRow[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    api.listPapers().then(setPapers).catch(() => setPapers([]));
  }, []);

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return papers;
    return papers.filter((paper) =>
      `${paper.title} ${paper.source}`.toLocaleLowerCase().includes(needle)
    );
  }, [papers, query]);

  const toggle = (paperId: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(paperId)) next.delete(paperId);
      else next.add(paperId);
      return next;
    });
  };

  const compareHref = `/compare?papers=${Array.from(selected).join(",")}`;

  return (
    <main className="min-h-screen px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <div className="mx-auto max-w-[1050px]">
        <header className="mb-8 flex flex-wrap items-end justify-between gap-5">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--pl-clay)]">
              Your papers
            </p>
            <h1 className="mt-2 text-3xl font-medium tracking-[-0.03em]">论文库</h1>
            <p className="mt-2 max-w-xl text-sm leading-6 text-[var(--pl-muted)]">
              所有阅读从论文开始。打开一篇继续阅读，或选择多篇进入对比模式。
            </p>
          </div>
          <Link
            href="/"
            className="inline-flex h-10 items-center rounded-lg bg-[var(--pl-ink)] px-4 text-xs font-medium text-white transition hover:bg-black"
          >
            ＋ 导入论文
          </Link>
        </header>

        <section className="overflow-hidden rounded-2xl border border-[var(--pl-line)] bg-white/70 shadow-[0_12px_30px_rgba(44,39,31,.04)]">
          <div className="flex flex-wrap items-center gap-3 border-b border-[var(--pl-line)] bg-[#fbfaf7] p-3">
            <label className="relative min-w-[220px] flex-1">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-xs text-[var(--pl-faint)]">⌕</span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="按标题或来源搜索…"
                className="h-9 w-full rounded-lg border border-[var(--pl-line)] bg-white pl-8 pr-3 text-xs outline-none transition focus:border-[var(--pl-clay)]"
              />
            </label>
            <span className="font-mono text-[9px] uppercase tracking-wide text-[var(--pl-faint)]">
              {filtered.length} papers
            </span>
            {selected.size > 0 && (
              <>
                <button
                  type="button"
                  onClick={() => setSelected(new Set())}
                  className="text-xs text-[var(--pl-muted)] hover:text-[var(--pl-ink)]"
                >
                  清除 {selected.size} 项
                </button>
                <Link
                  href={compareHref}
                  className="inline-flex h-9 items-center rounded-lg bg-[var(--pl-clay)] px-3.5 text-xs font-medium text-white transition hover:bg-[var(--pl-clay-dark)]"
                >
                  对比所选论文 →
                </Link>
              </>
            )}
          </div>

          {filtered.length === 0 ? (
            <div className="px-6 py-16 text-center">
              <p className="text-sm font-medium">{papers.length === 0 ? "还没有论文" : "没有匹配的论文"}</p>
              <p className="mt-1 text-xs text-[var(--pl-faint)]">
                {papers.length === 0 ? "导入 PDF 或 arXiv 链接后即可开始阅读。" : "试试更短的标题关键词。"}
              </p>
            </div>
          ) : (
            <div className="divide-y divide-[var(--pl-line)]">
              {filtered.map((paper, index) => {
                const checked = selected.has(paper.paper_id);
                return (
                  <article
                    key={paper.paper_id}
                    className={`group grid grid-cols-[32px_36px_minmax(0,1fr)_auto] items-center gap-3 px-4 py-4 transition ${
                      checked ? "bg-[#f7eee9]" : "hover:bg-white"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => toggle(paper.paper_id)}
                      aria-label={checked ? `取消选择 ${paper.title}` : `选择 ${paper.title}`}
                      aria-pressed={checked}
                      className={`grid size-5 place-items-center rounded border text-[10px] transition ${
                        checked
                          ? "border-[var(--pl-clay)] bg-[var(--pl-clay)] text-white"
                          : "border-[var(--pl-line-strong)] bg-white text-transparent group-hover:text-[var(--pl-faint)]"
                      }`}
                    >
                      ✓
                    </button>
                    <span className="font-mono text-[10px] text-[var(--pl-faint)]">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <Link href={`/paper/${paper.paper_id}`} className="min-w-0">
                      <h2 className="truncate text-[13px] font-medium tracking-[-0.01em] group-hover:text-[var(--pl-clay)]">
                        {paper.title || paper.paper_id.slice(0, 12)}
                      </h2>
                      <p className="mt-1 font-mono text-[9px] uppercase tracking-wide text-[var(--pl-faint)]">
                        {paper.source} · {paper.versions} {paper.versions === 1 ? "version" : "versions"}
                      </p>
                    </Link>
                    <Link
                      href={`/paper/${paper.paper_id}`}
                      className="rounded-lg px-3 py-2 text-xs text-[var(--pl-muted)] opacity-0 transition hover:bg-[#f1eee8] hover:text-[var(--pl-ink)] group-hover:opacity-100 focus:opacity-100"
                    >
                      打开阅读
                    </Link>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
