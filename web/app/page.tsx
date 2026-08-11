"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type JobInfo, type PaperRow } from "@/lib/api";

const STAGES = [
  ["file_validation", "文件校验"],
  ["metadata_and_pages", "元数据与页面"],
  ["layout_and_text", "版面与文字解析"],
  ["sections", "章节结构识别"],
  ["assets", "图表与公式提取"],
  ["references", "参考文献解析"],
  ["index", "检索索引建立"],
  ["initial_translation", "初始翻译"],
] as const;

export default function HomePage() {
  const [papers, setPapers] = useState<PaperRow[]>([]);
  const [arxivInput, setArxivInput] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [job, setJob] = useState<JobInfo | null>(null);
  const [matchedArxiv, setMatchedArxiv] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => {
    api.listPapers().then(setPapers).catch(() => setPapers([]));
  }, []);

  useEffect(() => refresh(), [refresh]);

  const watchJob = useCallback((jobId: string) => {
    setBusy(true);
    setError("");
    const poll = async () => {
      try {
        const info = await api.job(jobId);
        setJob(info);
        if (info.status === "SUCCEEDED") {
          refresh();
          if (info.paper_id) window.location.href = `/paper/${info.paper_id}`;
          return;
        }
        if (info.status === "FAILED") {
          setError(info.error_message || "解析失败");
          setBusy(false);
          return;
        }
        window.setTimeout(() => void poll(), 1200);
      } catch (err) {
        setError(err instanceof Error ? err.message : "无法读取解析状态");
        setBusy(false);
      }
    };
    void poll();
  }, [refresh]);

  const upload = async (file: File) => {
    if (busy) return;
    setError("");
    try {
      const result = await api.upload(file);
      setMatchedArxiv(result.matched_arxiv ? `已匹配 arXiv ${result.matched_arxiv}` : "");
      watchJob(result.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    }
  };

  const importArxiv = async () => {
    if (busy || !arxivInput.trim()) return;
    setError("");
    try {
      const result = await api.importArxiv(arxivInput.trim());
      watchJob(result.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入失败");
    }
  };

  const progress = Math.round((job?.progress ?? 0) * 100);

  return (
    <main className="min-h-screen px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <div className="mx-auto max-w-[980px]">
        <header className="mb-8">
          <div>
            <h1 className="max-w-2xl text-[32px] font-semibold leading-tight tracking-[-0.035em] text-[var(--pl-ink)] sm:text-[38px]">
              读一篇论文
            </h1>
            <p className="mt-2 text-sm text-[var(--pl-muted)]">导入 PDF 或 arXiv 链接，开始结构化阅读与证据问答。</p>
          </div>
        </header>

        <section
          className={`overflow-hidden rounded-2xl border bg-white shadow-[0_12px_35px_rgba(47,42,34,.07)] transition ${
            dragOver ? "border-[var(--pl-clay)] ring-4 ring-[rgba(185,87,56,.08)]" : "border-[var(--pl-line)]"
          }`}
          onDragOver={(event) => { event.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragOver(false);
            const file = event.dataTransfer.files?.[0];
            if (file) void upload(file);
          }}
        >
          <label htmlFor="paper-source" className="sr-only">arXiv 链接或编号</label>
          <textarea
            id="paper-source"
            rows={4}
            value={arxivInput}
            onChange={(event) => setArxivInput(event.target.value)}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === "Enter") void importArxiv();
            }}
            placeholder="粘贴 arXiv 链接或编号，也可以把 PDF 拖到这里"
            className="block w-full resize-none border-0 bg-transparent px-6 pt-6 text-[15px] leading-6 text-[var(--pl-ink)] outline-none placeholder:text-[var(--pl-faint)]"
          />
          <div className="flex flex-wrap items-center gap-2 border-t border-[var(--pl-line)] bg-[#fbfaf7] px-3 py-3">
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={busy}
              className="flex h-9 items-center gap-2 rounded-lg border border-[var(--pl-line)] bg-white px-3 text-xs font-medium text-[var(--pl-muted)] transition hover:border-[var(--pl-line-strong)] hover:text-[var(--pl-ink)] disabled:opacity-40"
            >
              <span className="font-mono text-base leading-none">＋</span> 添加 PDF
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
              }}
            />
            <span className="hidden text-[11px] text-[var(--pl-faint)] sm:inline">解析完成后直接进入阅读器</span>
            <button
              type="button"
              onClick={() => void importArxiv()}
              disabled={busy || !arxivInput.trim()}
              className="ml-auto flex h-9 items-center gap-2 rounded-lg bg-[var(--pl-ink)] px-4 text-xs font-medium text-white transition hover:bg-black disabled:cursor-not-allowed disabled:opacity-35"
            >
              {busy ? "处理中" : "开始解析"}<span aria-hidden>↵</span>
            </button>
          </div>
        </section>

        {(job || error || matchedArxiv) && (
          <section className="mt-4 rounded-xl border border-[var(--pl-line)] bg-white/70 p-4">
            {error ? (
              <p className="text-sm text-[#a23f32]">{error}</p>
            ) : (
              <>
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium text-[var(--pl-ink)]">
                    {matchedArxiv || "正在构建论文结构与证据索引"}
                  </span>
                  <span className="font-mono text-[var(--pl-clay)]">{progress}%</span>
                </div>
                <div className="mt-3 h-1 overflow-hidden rounded-full bg-[var(--pl-line)]">
                  <div className="h-full bg-[var(--pl-clay)] transition-all duration-500" style={{ width: `${progress}%` }} />
                </div>
                {job && (
                  <details className="mt-3 text-xs text-[var(--pl-muted)]">
                    <summary className="cursor-pointer select-none text-[11px] text-[var(--pl-faint)]">查看解析细节</summary>
                    <div className="mt-3 grid gap-1.5 sm:grid-cols-2">
                    {STAGES.filter(([key]) => job.stages[key]).map(([key, label]) => {
                      const status = job.stages[key]?.status;
                      return (
                        <div key={key} className="flex items-center gap-2 font-mono text-[10px] text-[var(--pl-muted)]">
                          <span className={status === "SUCCEEDED" || status === "RUNNING" ? "text-[var(--pl-clay)]" : "text-[var(--pl-faint)]"}>
                            {status === "SUCCEEDED" ? "✓" : status === "RUNNING" ? "●" : "○"}
                          </span>
                          {label}
                        </div>
                      );
                    })}
                    </div>
                  </details>
                )}
              </>
            )}
          </section>
        )}

        <div className="mt-12">
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--pl-muted)]">最近论文</h2>
              <Link href="/library" className="text-xs text-[var(--pl-muted)] hover:text-[var(--pl-clay)]">查看资料库 →</Link>
            </div>
            {papers.length === 0 ? (
              <div className="rounded-xl border border-dashed border-[var(--pl-line-strong)] px-5 py-8 text-center text-sm text-[var(--pl-faint)]">
                还没有论文。导入第一篇，PaperLens 会保留结构、证据与版本。
              </div>
            ) : (
              <div className="divide-y divide-[var(--pl-line)] border-y border-[var(--pl-line)]">
                {papers.slice(0, 6).map((paper, index) => (
                  <Link key={paper.paper_id} href={`/paper/${paper.paper_id}`} className="group grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-3 py-3.5">
                    <span className="font-mono text-[10px] text-[var(--pl-faint)]">{String(index + 1).padStart(2, "0")}</span>
                    <span className="truncate text-[13px] font-medium group-hover:text-[var(--pl-clay)]">{paper.title || paper.paper_id.slice(0, 12)}</span>
                    <span className="font-mono text-[9px] uppercase text-[var(--pl-faint)]">{paper.source} · v{paper.versions}</span>
                  </Link>
                ))}
              </div>
            )}
          </section>

        </div>
      </div>
    </main>
  );
}
