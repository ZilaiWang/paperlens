"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { deleteTerm, listTermbase, upsertTerm, type TermEntry } from "@/lib/apiV2";

const scopeLabel: Record<string, string> = {
  SYSTEM: "系统", DOMAIN: "领域", PROJECT: "项目", PAPER: "论文", USER: "用户",
};

export default function TermsPage() {
  const [terms, setTerms] = useState<TermEntry[]>([]);
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [locked, setLocked] = useState(false);
  const [keepEnglish, setKeepEnglish] = useState(false);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(() => {
    listTermbase().then(setTerms).catch((err) => setError(err instanceof Error ? err.message : "术语加载失败"));
  }, []);
  useEffect(() => refresh(), [refresh]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return needle ? terms.filter((term) => `${term.source} ${term.target}`.toLocaleLowerCase().includes(needle)) : terms;
  }, [query, terms]);

  const addTerm = async () => {
    if (busy || !source.trim() || (!target.trim() && !keepEnglish)) return;
    setBusy(true);
    setError("");
    try {
      await upsertTerm({ source: source.trim(), target: keepEnglish ? "" : target.trim(), scope: "PROJECT", locked, keep_english: keepEnglish });
      setSource(""); setTarget(""); setLocked(false); setKeepEnglish(false);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "添加术语失败");
    } finally { setBusy(false); }
  };

  const removeTerm = async (term: TermEntry) => {
    if (["SYSTEM", "DOMAIN"].includes(term.scope)) return;
    setError("");
    try {
      await deleteTerm(term.scope, term.source);
      setTerms((items) => items.filter((item) => !(item.scope === term.scope && item.source === term.source)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除术语失败");
    }
  };

  return (
    <main className="min-h-screen px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <div className="mx-auto max-w-[1050px]">
        <header className="mb-9 flex flex-wrap items-end justify-between gap-5">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--pl-clay)]">Settings / Translation</p>
            <h1 className="mt-2 text-3xl font-medium tracking-[-0.03em]">翻译设置与术语</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--pl-muted)]">这是阅读器的内部翻译能力。内置领域词表会自动参与翻译，你也可以在这里补充固定译法。</p>
          </div>
          <div className="flex gap-5 font-mono text-[9px] uppercase tracking-wide text-[var(--pl-faint)]">
            <span><b className="mr-1 text-sm font-medium text-[var(--pl-ink)]">{terms.length}</b> total</span>
            <span><b className="mr-1 text-sm font-medium text-[var(--pl-ink)]">{terms.filter((term) => term.locked).length}</b> locked</span>
          </div>
        </header>

        <div className="grid gap-8 lg:grid-cols-[330px_minmax(0,1fr)]">
          <aside className="lg:sticky lg:top-10 lg:self-start">
            <div className="rounded-2xl border border-[var(--pl-line)] bg-white p-5 shadow-[0_10px_28px_rgba(44,39,31,.06)]">
              <div className="mb-5 flex items-center justify-between"><h2 className="text-sm font-medium">添加自定义术语</h2><span className="font-mono text-[9px] text-[var(--pl-faint)]">WORKSPACE</span></div>
              <label className="block text-[11px] font-medium text-[var(--pl-muted)]">原文<input value={source} onChange={(event) => setSource(event.target.value)} placeholder="backbone" className="mt-2 block w-full rounded-lg border border-[var(--pl-line)] bg-[#fbfaf7] px-3 py-2.5 text-sm outline-none focus:border-[var(--pl-clay)]" /></label>
              <label className="mt-4 block text-[11px] font-medium text-[var(--pl-muted)]">目标译法<input value={target} disabled={keepEnglish} onChange={(event) => setTarget(event.target.value)} placeholder={keepEnglish ? "保持原文" : "骨干网络"} className="mt-2 block w-full rounded-lg border border-[var(--pl-line)] bg-[#fbfaf7] px-3 py-2.5 text-sm outline-none focus:border-[var(--pl-clay)] disabled:text-[var(--pl-faint)]" /></label>
              <div className="mt-4 space-y-2 text-xs text-[var(--pl-muted)]">
                <label className="flex cursor-pointer items-center gap-2"><input type="checkbox" checked={locked} onChange={(event) => setLocked(event.target.checked)} className="accent-[var(--pl-clay)]" />锁定译法</label>
                <label className="flex cursor-pointer items-center gap-2"><input type="checkbox" checked={keepEnglish} onChange={(event) => setKeepEnglish(event.target.checked)} className="accent-[var(--pl-clay)]" />保持英文</label>
              </div>
              {error && <p className="mt-3 text-xs text-[#a23f32]">{error}</p>}
              <button type="button" onClick={() => void addTerm()} disabled={busy || !source.trim() || (!target.trim() && !keepEnglish)} className="mt-5 h-10 w-full rounded-lg bg-[var(--pl-ink)] text-xs font-medium text-white hover:bg-black disabled:opacity-35">{busy ? "保存中…" : "保存术语 →"}</button>
            </div>
            <div className="mt-3 rounded-xl border border-[var(--pl-line)] p-4 text-[11px] leading-5 text-[var(--pl-faint)]">内部优先级：个人规则 → 当前论文 → 工作区 → 领域词表 → 系统词表。系统和领域词表只读，避免局部修改影响基础译法。</div>
          </aside>

          <section>
            <div className="mb-3 flex items-center gap-3">
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索原文或译法…" className="h-9 min-w-0 flex-1 rounded-lg border border-[var(--pl-line)] bg-white/70 px-3 text-xs outline-none focus:border-[var(--pl-clay)]" />
              <span className="font-mono text-[9px] uppercase text-[var(--pl-faint)]">{filtered.length} entries</span>
            </div>
            <div className="overflow-hidden rounded-xl border border-[var(--pl-line)] bg-white/70">
              <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_90px_28px] gap-3 border-b border-[var(--pl-line)] bg-[#f1efe9] px-4 py-2.5 font-mono text-[9px] uppercase tracking-wide text-[var(--pl-faint)]"><span>Source</span><span>Target</span><span>Scope</span><span /></div>
              {filtered.length === 0 ? <p className="px-5 py-12 text-center text-sm text-[var(--pl-faint)]">没有匹配的术语。</p> : filtered.map((term) => {
                const editable = !["SYSTEM", "DOMAIN"].includes(term.scope);
                return (
                  <div key={`${term.scope}:${term.source}`} className="group grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_90px_28px] items-center gap-3 border-b border-[var(--pl-line)] px-4 py-3 last:border-0">
                    <div className="truncate text-[13px] font-medium">{term.source}</div>
                    <div className="flex min-w-0 items-center gap-2"><span className="truncate text-[13px] text-[var(--pl-muted)]">{term.target || term.source}</span>{term.locked && <span title="已锁定" className="font-mono text-[9px] text-[var(--pl-clay)]">LOCK</span>}</div>
                    <span className="w-fit rounded bg-[#eeeae2] px-1.5 py-1 font-mono text-[8px] uppercase text-[var(--pl-muted)]">{scopeLabel[term.scope] ?? term.scope}</span>
                    <button type="button" disabled={!editable} title={editable ? "删除术语" : "内置术语只读"} onClick={() => void removeTerm(term)} className="text-[var(--pl-faint)] opacity-0 transition hover:text-[#a23f32] disabled:cursor-default group-hover:opacity-100 disabled:opacity-0">×</button>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
