"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  deleteTerm,
  installTermPack,
  listTermbase,
  listTermPacks,
  uninstallTermPack,
  upsertTerm,
  type TermEntry,
  type TermPack,
} from "@/lib/apiV2";

export default function TranslationSettingsPage() {
  const [packs, setPacks] = useState<TermPack[]>([]);
  const [terms, setTerms] = useState<TermEntry[]>([]);
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [packRows, termRows] = await Promise.all([listTermPacks(), listTermbase()]);
      setPacks(packRows);
      setTerms(termRows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "翻译设置加载失败");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const overrides = useMemo(
    () => terms.filter((term) => !["SYSTEM", "DOMAIN"].includes(term.scope)),
    [terms],
  );

  const togglePack = async (pack: TermPack) => {
    setBusy(pack.pack_id);
    setError("");
    try {
      if (pack.installed) await uninstallTermPack(pack.pack_id);
      else await installTermPack(pack.pack_id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "术语包更新失败");
    } finally { setBusy(""); }
  };

  const saveOverride = async () => {
    if (!source.trim() || !target.trim()) return;
    setBusy("override");
    try {
      await upsertTerm({ source: source.trim(), target: target.trim(), scope: "USER", locked: true });
      setSource(""); setTarget("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "个人译法保存失败");
    } finally { setBusy(""); }
  };

  return (
    <main className="min-h-screen px-5 py-9 sm:px-9">
      <div className="mx-auto max-w-[900px]">
        <Link href="/library" className="text-xs text-[var(--pl-muted)] hover:text-[var(--pl-clay)]">← 返回论文库</Link>
        <header className="mt-7 border-b border-[var(--pl-line)] pb-6">
          <h1 className="text-3xl font-semibold tracking-[-0.03em]">翻译设置</h1>
          <p className="mt-2 text-sm leading-6 text-[var(--pl-muted)]">安装领域术语包后，译文会自动采用一致的专业表达。个人译法只覆盖你明确指定的词。</p>
        </header>

        {error && <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}

        <section className="mt-8">
          <div className="mb-3 flex items-end justify-between"><div><h2 className="text-base font-medium">领域术语包</h2><p className="mt-1 text-xs text-[var(--pl-faint)]">按研究方向安装，需要时可以随时停用。</p></div><span className="text-xs text-[var(--pl-faint)]">已安装 {packs.filter((pack) => pack.installed).length}</span></div>
          <div className="grid gap-3 sm:grid-cols-2">
            {packs.map((pack) => (
              <article key={pack.pack_id} className="rounded-xl border border-[var(--pl-line)] bg-white p-4">
                <div className="flex items-start justify-between gap-4"><div><h3 className="text-sm font-medium">{pack.name}</h3><p className="mt-1 text-xs leading-5 text-[var(--pl-muted)]">{pack.description}</p></div><button type="button" disabled={busy === pack.pack_id} onClick={() => void togglePack(pack)} className={`shrink-0 rounded-lg px-3 py-1.5 text-xs ${pack.installed ? "border border-[var(--pl-line)] text-[var(--pl-muted)]" : "bg-[var(--pl-clay)] text-white"}`}>{busy === pack.pack_id ? "更新中…" : pack.installed ? "已安装" : "安装"}</button></div>
                <p className="mt-3 text-[10px] text-[var(--pl-faint)]">{pack.term_count} 个术语 · v{pack.version} · {pack.license}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="mt-10 border-t border-[var(--pl-line)] pt-8">
          <h2 className="text-base font-medium">个人译法覆盖</h2>
          <p className="mt-1 text-xs text-[var(--pl-faint)]">只在系统译法不符合你的习惯时添加，优先级高于术语包。</p>
          <div className="mt-4 flex flex-col gap-2 sm:flex-row"><input value={source} onChange={(event) => setSource(event.target.value)} placeholder="原文，例如 backbone" className="h-10 flex-1 rounded-lg border border-[var(--pl-line)] bg-white px-3 text-sm outline-none focus:border-[var(--pl-clay)]" /><input value={target} onChange={(event) => setTarget(event.target.value)} placeholder="你的译法" className="h-10 flex-1 rounded-lg border border-[var(--pl-line)] bg-white px-3 text-sm outline-none focus:border-[var(--pl-clay)]" /><button type="button" disabled={busy === "override" || !source.trim() || !target.trim()} onClick={() => void saveOverride()} className="h-10 rounded-lg bg-[var(--pl-ink)] px-4 text-xs text-white disabled:opacity-40">保存覆盖</button></div>
          <div className="mt-4 divide-y divide-[var(--pl-line)] border-y border-[var(--pl-line)]">
            {overrides.length === 0 ? <p className="py-6 text-center text-xs text-[var(--pl-faint)]">暂无个人覆盖</p> : overrides.map((term) => <div key={`${term.scope}:${term.source}`} className="flex items-center gap-3 py-3 text-sm"><span className="min-w-0 flex-1 truncate">{term.source}</span><span className="min-w-0 flex-1 truncate text-[var(--pl-muted)]">{term.target || term.source}</span><button type="button" onClick={async () => { await deleteTerm(term.scope, term.source); await refresh(); }} className="text-xs text-[var(--pl-faint)] hover:text-red-600">删除</button></div>)}
          </div>
        </section>
      </div>
    </main>
  );
}
