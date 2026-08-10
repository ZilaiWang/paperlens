"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, type JobInfo, type PaperRow } from "@/lib/api";

export default function HomePage() {
  const [papers, setPapers] = useState<PaperRow[]>([]);
  const [arxivInput, setArxivInput] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [job, setJob] = useState<JobInfo | null>(null);
  const [matchedArxiv, setMatchedArxiv] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  // 倒计时状态机（V3.11，邪门方案）：
  // - 从第一次轮询就显示（起步 60s 的合理猜测，不追求精确）
  // - 每轮只减不增（单调递减，杜绝"越数越多"）
  // - 服务端进度估算只允许向下修正（更准时跳低，不准时保持递减）
  // - job 结束（SUCCEEDED）时清零隐藏
  const etaRef = useRef<number | null>(null);
  const etaTickRef = useRef<number>(Date.now());
  // 滑动窗口进度历史：供服务端斜率估算
  const progressHistoryRef = useRef<{ t: number; p: number }[]>([]);

  const updateEta = useCallback((progress: number, status: string) => {
    const now = Date.now();
    const dt = Math.max(0, (now - etaTickRef.current) / 1000);
    etaTickRef.current = now;
    if (status === "SUCCEEDED" || progress >= 0.99) {
      etaRef.current = null;
      return;
    }
    // 起步猜测：解析+翻译一篇论文 ~40s（HTML 论文略长，PDF 略短）
    if (etaRef.current === null) {
      etaRef.current = 40;
      return;
    }
    // 服务端斜率估算（若有可靠数据），只允许向下修正
    let estimated: number | null = null;
    const history = progressHistoryRef.current;
    if (history.length >= 3) {
      const first = history[0];
      const last = history[history.length - 1];
      const window = (last.t - first.t) / 1000;
      const delta = last.p - first.p;
      if (window >= 3 && delta > 0.001 && last.p > 0.05) {
        estimated = (1 - last.p) / (delta / window);
      }
    }
    const decremented = Math.max((etaRef.current ?? 0) - dt, 0);
    etaRef.current =
      estimated !== null && estimated < decremented
        ? Math.max(estimated, 5) // 向下修正，保底 5s
        : decremented; // 无估算或估算更慢 → 保持单调递减
  }, []);

  const refresh = useCallback(() => {
    api.listPapers().then(setPapers).catch(() => setPapers([]));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Follow a parse job; navigate to the paper when it succeeds.
  // The job carries paper_id, so we never guess from list order; progressive
  // translation happens inside the workbench instead of blocking the entry.
  const watchJob = useCallback(
    (jobId: string) => {
      setBusy(true);
      setError("");
      const poll = async () => {
        const info = await api.job(jobId);
        // 只记录递增的进度点（跳过无变化轮询），保留最近 8 个
        const history = progressHistoryRef.current;
        const last = history[history.length - 1];
        if (!last || info.progress > last.p) {
          history.push({ t: Date.now(), p: info.progress });
          if (history.length > 8) history.shift();
        }
        updateEta(info.progress, info.status);
        setJob(info);
        if (info.status === "SUCCEEDED") {
          refresh();
          if (info.paper_id) {
            window.location.href = `/paper/${info.paper_id}`;
          } else {
            const rows = await api.listPapers();
            const paper = rows[0];
            if (paper) window.location.href = `/paper/${paper.paper_id}`;
          }
          return;
        }
        if (info.status === "FAILED") {
          setError(info.error_message || "解析失败");
          setBusy(false);
          return;
        }
        setTimeout(poll, 1200);
      };
      void poll();
    },
    [refresh]
  );

  const upload = async (file: File) => {
    if (busy) return;
    try {
      const result = await api.upload(file);
      // 上传时会自动按文件名/标题搜 arXiv：
      // 命中 HTML 版本就走语义解析，否则回退 PDF 管线
      setMatchedArxiv(
        result.matched_arxiv ? `已匹配 arXiv ${result.matched_arxiv}，使用语义解析` : ""
      );
      watchJob(result.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    }
  };

  const importArxiv = async () => {
    if (busy || !arxivInput.trim()) return;
    try {
      const result = await api.importArxiv(arxivInput.trim());
      watchJob(result.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入失败");
    }
  };

  const stageOrder = [
    "file_validation",
    "metadata_and_pages",
    "layout_and_text",
    "sections",
    "assets",
    "references",
    "index",
    "initial_translation",
  ];
  const stageLabels: Record<string, string> = {
    file_validation: "文件校验",
    metadata_and_pages: "元数据与页面",
    layout_and_text: "版面与文字解析",
    sections: "章节结构识别",
    assets: "图表与公式提取",
    references: "参考文献解析",
    index: "检索索引建立",
    initial_translation: "正在翻译",
  };

  return (
    <main className="flex-1 flex flex-col items-center px-6 pt-20 pb-16">
      {/* header */}
      <header className="w-full max-w-3xl flex items-center justify-between mb-14">
        <span className="text-xl font-semibold tracking-tight">PaperLens</span>
        <nav className="flex items-center gap-5 text-sm text-[#6b7280]">
          <span className="text-[#202124] font-medium">单篇阅读</span>
          <Link href="/compare" className="hover:text-[#2f4b7c]">
            多篇比较
          </Link>
        </nav>
      </header>

      {/* hero */}
      <div className="text-center mb-12">
        <h1 className="text-4xl font-semibold tracking-tight leading-tight">
          Read a paper deeply.
        </h1>
      </div>

      {/* import card */}
      <div
        className={`w-full max-w-2xl bg-white rounded-2xl border p-8 transition-colors ${
          dragOver ? "border-[#2f4b7c] border-2" : "border-[#e6e7ea]"
        }`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragOver(false);
          const file = event.dataTransfer.files?.[0];
          if (file) void upload(file);
        }}
      >
        <button
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          className="w-full py-8 rounded-xl border border-dashed border-[#d0d3d8] text-[#6b7280] hover:border-[#2f4b7c] hover:text-[#2f4b7c] transition-colors disabled:opacity-50"
        >
          <div className="text-2xl mb-2">⇪</div>
          <div>拖入 PDF，或点击选择文件</div>
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

        <div className="flex items-center gap-3 mt-5">
          <div className="h-px flex-1 bg-[#e6e7ea]" />
          <span className="text-xs text-[#9aa0a6]">或</span>
          <div className="h-px flex-1 bg-[#e6e7ea]" />
        </div>

        <div className="flex gap-2 mt-5">
          <input
            value={arxivInput}
            onChange={(event) => setArxivInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void importArxiv();
            }}
            placeholder="arXiv 链接 / arXiv ID，如 2507.02798"
            className="flex-1 px-4 py-2.5 rounded-lg border border-[#e6e7ea] text-sm focus:outline-none focus:border-[#2f4b7c]"
          />
          <button
            onClick={() => void importArxiv()}
            disabled={busy || !arxivInput.trim()}
            className="px-5 py-2.5 rounded-lg bg-[#2f4b7c] text-white text-sm hover:bg-[#263d64] disabled:opacity-40 transition-colors"
          >
            解析论文
          </button>
        </div>
      </div>

      {/* 上传匹配 arXiv 提示（Source-first） */}
      {matchedArxiv && (
        <div className="w-full max-w-2xl mt-6 bg-white rounded-2xl border border-[#e6e7ea] p-4 text-sm text-[#2f4b7c]">
          ⟳ {matchedArxiv}…
        </div>
      )}
      {job && (
        <div className="w-full max-w-2xl mt-6 bg-white rounded-2xl border border-[#e6e7ea] p-6">
          <div className="flex justify-between text-sm mb-3">
            <span className="font-medium">正在解析</span>
            <span className="flex items-center gap-3">
              {/* 预计剩余时间（V3.11）：单调递减状态机——起步 60s，
                  只减不增，服务端估算更准时向下修正 */}
              {etaRef.current !== null && etaRef.current > 0 && (
                <span className="text-xs text-[#9aa0a6] tabular-nums">
                  预计剩余 {Math.round(etaRef.current)}s
                </span>
              )}
              <span className="text-[#2f4b7c]">{Math.round(job.progress * 100)}%</span>
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-[#eceef1] overflow-hidden">
            <div
              className="h-full bg-[#2f4b7c] transition-all duration-500"
              style={{ width: `${Math.round(job.progress * 100)}%` }}
            />
          </div>
          <ul className="mt-4 space-y-1.5 text-sm text-[#6b7280]">
            {/* 只显示 job 实际包含的 stage：匹配到 HTML 后无用的条目不展示（V3.7） */}
            {stageOrder.filter((key) => job.stages[key]).map((key) => {
              const stage = job.stages[key];
              const done = stage?.status === "SUCCEEDED";
              const active = stage?.status === "RUNNING";
              const queued = stage?.status === "QUEUED";
              // 每步耗时（日志系统 V3.6：stage 时间戳，快速定位慢在哪）
              let duration = "";
              if (stage?.started_at && stage.finished_at) {
                const seconds =
                  (new Date(stage.finished_at).getTime() -
                    new Date(stage.started_at).getTime()) /
                  1000;
                if (seconds > 0.05) duration = `${seconds.toFixed(1)}s`;
              }
              return (
                <li key={key} className="flex items-center gap-2">
                  <span
                    className={
                      done || active
                        ? "text-[#2f4b7c]"
                        : queued
                          ? "text-[#d0d3d8]"
                          : ""
                    }
                  >
                    {done ? "✓" : active ? "●" : "○"}
                  </span>
                  <span className={queued ? "text-[#9aa0a6]" : ""}>
                    {stageLabels[key] ?? key}
                  </span>
                  {stage?.detail && (
                    <span className="text-xs text-[#9aa0a6]">{stage.detail}</span>
                  )}
                  {queued && (
                    <span className="text-xs text-[#d0d3d8]">待开始</span>
                  )}
                  {duration && (
                    <span className="text-xs text-[#9aa0a6] ml-auto tabular-nums">
                      {duration}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {error && (
        <div className="mt-4 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-4 py-2.5">
          {error}
        </div>
      )}

      {/* recent papers */}
      <section className="w-full max-w-2xl mt-14">
        <h2 className="text-sm text-[#6b7280] mb-3">最近阅读</h2>
        {papers.length === 0 ? (
          <p className="text-sm text-[#9aa0a6]">还没有解析过的论文</p>
        ) : (
          <div className="grid gap-2">
            {papers.map((paper) => (
              <Link
                key={paper.paper_id}
                href={`/paper/${paper.paper_id}`}
                className="group flex items-center justify-between bg-white border border-[#e6e7ea] rounded-xl px-5 py-3.5 hover:border-[#2f4b7c] transition-colors"
              >
                <span className="text-sm font-medium truncate group-hover:text-[#2f4b7c]">
                  {paper.title || paper.paper_id.slice(0, 12)}
                </span>
                <span className="text-xs text-[#9aa0a6] shrink-0 ml-4">
                  {paper.source} · {paper.versions} 版本
                </span>
              </Link>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
