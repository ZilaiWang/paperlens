"use client";

// V4.7f 多篇比较（体验版）：字段中文化 + 视觉升级 + 引文翻译 + 对话式问答。
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, type PaperRow } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8700";

// V4.7f：字段中文化（用户可读，替代内部英文键）
const FIELD_LABELS: Record<string, { label: string; hint: string; group: string }> = {
  task_definition: { label: "任务定义", hint: "论文在解决什么问题", group: "概览" },
  research_question: { label: "研究问题", hint: "动机与主要贡献", group: "概览" },
  method_core: { label: "方法核心", hint: "核心方法/架构/创新点", group: "方法" },
  training_setup: { label: "训练设置", hint: "优化器/冻结/轮数等", group: "方法" },
  inference_setup: { label: "推理设置", hint: "测试/预测配置", group: "方法" },
  datasets_and_samples: { label: "数据集", hint: "评测数据与划分", group: "实验" },
  metrics: { label: "评估指标", hint: "AP/mAcc 等", group: "实验" },
  main_results: { label: "主要结果", hint: "核心性能数字", group: "实验" },
  ablations: { label: "消融实验", hint: "组件贡献分析", group: "实验" },
  baselines: { label: "基线对比", hint: "与 SOTA/基线的比较", group: "实验" },
  author_limitations: { label: "局限", hint: "作者承认的不足", group: "概览" },
  code_and_data: { label: "代码与数据", hint: "开源与复现资源", group: "复现" },
  version_status: { label: "版本状态", hint: "期刊/会议版本", group: "复现" },
};

const FIELD_GROUPS = ["概览", "方法", "实验", "复现"];

interface Cell {
  paper_id: string;
  field: string;
  value: string;
  status: string;
  evidence_ids: string[];
  note: string;
  quotes: string[];
  locators: Array<{ page: number; section: string; block_ids: string[] }>;
}

interface ComparisonResult {
  comparison_id: string;
  status: string;
  paper_version_ids: string[];
  stage?: string;
  progress?: number;
  cached?: boolean;
  error?: string;
  alignment: {
    alignment: string;
    rationale: string;
    confidence: number;
    evidence_fields: string[];
  };
  table: { paper_ids: string[]; fields: string[]; cells: Cell[]; warnings: string[] };
  result_comparisons: Array<{
    dataset: string;
    metric: string;
    conditions: Record<string, string>;
    values: Record<string, string>;
    same_key: boolean;
    best_paper: string;
  }>;
  // 2026-08-06：单元格中文翻译（key = `${paper_id}|${field}`）
  cell_translations?: Record<string, string>;
  created_at: string;
}

interface QAMessage {
  role: "user" | "assistant";
  content: string;
  comparability?: string;
  paperEvidence?: Record<string, string[]>;
}

const ALIGNMENT_BADGE: Record<string, { label: string; cls: string }> = {
  SAME_TASK: { label: "同任务 · 可数值比较", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  RELATED: { label: "相近任务 · 方法对照", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  DIFFERENT: { label: "任务不同 · 不建议比较数值", cls: "bg-red-50 text-red-700 border-red-200" },
};

const CELL_STATUS: Record<string, { label: string; cls: string }> = {
  FOUND: { label: "有证据", cls: "text-emerald-600" },
  NOT_FOUND_IN_SEARCHED_SECTIONS: { label: "未找到", cls: "text-[#9aa0a6]" },
  NOT_REPORTED_CONFIRMED: { label: "确认未报告", cls: "text-[#9aa0a6] line-through" },
  UNASSESSABLE_PARSE_GAP: { label: "解析缺口", cls: "text-red-500" },
  NOT_APPLICABLE: { label: "不适用", cls: "text-[#9aa0a6]" },
};

export default function ComparePage() {
  return (
    <Suspense
      fallback={
        <main className="flex-1 flex items-center justify-center text-sm text-[#9aa0a6]">加载中…</main>
      }
    >
      <CompareContent />
    </Suspense>
  );
}

function CompareContent() {
  const searchParams = useSearchParams();
  const [papers, setPapers] = useState<PaperRow[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  // 2026-08-07（教师优化 2）：已选论文的摘要简介（meta 端点）
  const [paperMeta, setPaperMeta] = useState<Record<string, { abstract: string }>>({});
  const [running, setRunning] = useState<ComparisonResult | null>(null);
  const [result, setResult] = useState<ComparisonResult | null>(null);
  const [history, setHistory] = useState<Array<Record<string, unknown>>>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [error, setError] = useState("");
  // 引文翻译缓存：paperId → block_id → 译文
  const [translationsByPaper, setTranslationsByPaper] = useState<
    Record<string, Record<string, string>>
  >({});
  // 对话式问答
  const [qaMessages, setQaMessages] = useState<QAMessage[]>([]);
  const [qaInput, setQaInput] = useState("");
  const [qaBusy, setQaBusy] = useState(false);
  const [expandedCells, setExpandedCells] = useState<string>("");
  // 添加论文（上传/arXiv 导入）
  const [addOpen, setAddOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [arxivInput, setArxivInput] = useState("");
  const [jobStatus, setJobStatus] = useState("");
  const [jobProgress, setJobProgress] = useState(0);
  const jobTimerRef = useRef<number | null>(null);

  const watchJob = useCallback(
    (jobId: string) => {
      setJobStatus("已提交，等待解析…");
      setJobProgress(0);
      if (jobTimerRef.current) window.clearInterval(jobTimerRef.current);
      const poll = async () => {
        try {
          const job = await api.job(jobId);
          setJobProgress(job.progress);
          if (job.status === "SUCCEEDED") {
            setJobStatus("解析完成 ✓");
            if (jobTimerRef.current) window.clearInterval(jobTimerRef.current);
            const rows = await api.listPapers().catch(() => papers);
            setPapers(rows);
            if (job.paper_id) {
              setSelected((list) =>
                list.includes(job.paper_id) || list.length >= 3 ? list : [...list, job.paper_id]
              );
            }
          } else if (job.status === "FAILED") {
            setJobStatus(`解析失败：${job.error_message || job.error_code || "未知错误"}`);
            if (jobTimerRef.current) window.clearInterval(jobTimerRef.current);
          } else {
            jobTimerRef.current = window.setTimeout(() => void poll(), 1500);
          }
        } catch {
          jobTimerRef.current = window.setTimeout(() => void poll(), 1500);
        }
      };
      void poll();
    },
    [papers]
  );

  const upload = async (file: File) => {
    setError("");
    try {
      const result = await api.upload(file);
      setJobStatus(result.matched_arxiv ? `已匹配 arXiv ${result.matched_arxiv}` : "已提交 PDF");
      watchJob(result.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    }
  };

  const importArxiv = async () => {
    if (!arxivInput.trim()) return;
    setError("");
    try {
      const result = await api.importArxiv(arxivInput.trim());
      watchJob(result.job_id);
      setArxivInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入失败");
    }
  };

  const loadHistory = useCallback(() => {
    fetch(`${API}/api/v1/comparisons?limit=10`)
      .then((response) => response.json())
      .then(setHistory)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    api
      .listPapers()
      .then((rows) => {
        setPapers(rows);
        const preselect = searchParams.get("papers");
        if (preselect) {
          const ids = preselect.split(",").slice(0, 3);
          setSelected(ids.filter((id) => rows.some((row) => row.paper_id === id)));
        }
      })
      .catch(() => undefined);
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2026-08-07（教师优化 2）：选中论文变化时并行拉取摘要简介
  useEffect(() => {
    const pending = selected.filter((id) => !paperMeta[id]);
    if (pending.length === 0) return;
    let cancelled = false;
    for (const id of pending) {
      void api
        .meta(id)
        .then((meta) => {
          if (cancelled) return;
          setPaperMeta((map) => ({
            ...map,
            [id]: { abstract: meta.abstract ?? "" },
          }));
        })
        .catch(() => undefined);
    }
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  // 运行中轮询进度
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${API}/api/v1/comparisons/${running.comparison_id}`);
        const current = (await response.json()) as ComparisonResult;
        if (current.status === "DONE") {
          setResult(current);
          setRunning(null);
          loadHistory();
        } else if (current.status === "FAILED") {
          setError(`比较失败：${current.error ?? "未知错误"}`);
          setRunning(null);
        } else {
          // 404/中间态响应没有 comparison_id 时保留原 id 继续轮询
          //（修复 2026-08-05：此前会被覆盖成 undefined 永久卡住）
          setRunning((prev) => (current.comparison_id ? current : prev));
        }
      } catch {
        /* keep polling */
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [running, loadHistory]);

  const titleFor = (versionId: string) =>
    papers.find((paper) => paper.version_id === versionId)?.title || versionId.slice(0, 20);
  // 2026-08-07（教师优化 2）：已选论文对象（概览卡片用）
  const selectedPapers = papers.filter((paper) => selected.includes(paper.paper_id));
  const paperIdFor = (versionId: string) =>
    papers.find((paper) => paper.version_id === versionId)?.paper_id || versionId;
  const shortId = (versionId: string) => versionId.slice(0, 8);

  // 引文翻译：按论文拉取译文（HTML 全部在 page 1；PDF 按定位页）
  const fetchTranslations = useCallback(async (paperId: string, pages: number[]) => {
    try {
      const pageSet = [...new Set(pages.filter((page) => page > 0))];
      const all: Record<string, string> = {};
      for (const page of pageSet.length ? pageSet : [1]) {
        const units = await api.translations(paperId, page);
        for (const unit of units as Array<Record<string, unknown>>) {
          const blockIds = unit.source_block_ids as string[] | undefined;
          const target = String(unit.target_text ?? "");
          if (blockIds?.[0] && target) all[blockIds[0]] = target;
        }
      }
      setTranslationsByPaper((previous) => ({ ...previous, [paperId]: all }));
    } catch {
      /* translations are best-effort */
    }
  }, []);

  const translatedQuote = (paperId: string, blockIds: string[]) => {
    const map = translationsByPaper[paperId];
    if (!map) return "";
    for (const blockId of blockIds) {
      if (map[blockId]) return map[blockId];
    }
    return "";
  };

  // 2026-08-06：单元格中文翻译（后端比较完成时批量生成）
  const zhCell = (cell: Cell, versionId: string) =>
    result?.cell_translations?.[`${versionId}|${cell.field}`] ?? "";

  // 展开单元格时预取引文翻译
  const toggleCell = (cell: Cell, versionId: string) => {
    const key = `${versionId}-${cell.field}`;
    const willExpand = expandedCells !== key;
    setExpandedCells(willExpand ? key : "");
    if (willExpand && cell.locators.length > 0) {
      void fetchTranslations(paperIdFor(versionId), cell.locators.map((locator) => locator.page));
    }
  };

  const askQuestion = async () => {
    const question = qaInput.trim();
    if (!result || !question || qaBusy) return;
    setQaInput("");
    const nextMessages = [...qaMessages, { role: "user" as const, content: question }];
    setQaMessages(nextMessages);
    setQaBusy(true);
    try {
      const response = await fetch(
        `${API}/api/v1/comparisons/${result.comparison_id}/questions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question,
            history: qaMessages
              .slice(-6)
              .map((message) => ({ role: message.role, content: message.content })),
          }),
        }
      );
      if (!response.ok) throw new Error(`问答失败（${response.status}）`);
      const data = (await response.json()) as Record<string, unknown>;
      const answer = data.answer as Record<string, unknown>;
      setQaMessages([
        ...nextMessages,
        {
          role: "assistant",
          content: String(answer.claim ?? ""),
          comparability: String(answer.comparability_status ?? ""),
          paperEvidence: (answer.paper_evidence ?? {}) as Record<string, string[]>,
        },
      ]);
    } catch (err) {
      setQaMessages([...nextMessages, { role: "assistant", content: `出错了：${String(err)}` }]);
    } finally {
      setQaBusy(false);
    }
  };

  const exportMarkdown = async () => {
    if (!result) return;
    const response = await fetch(`${API}/api/v1/comparisons/${result.comparison_id}/export`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${result.comparison_id}.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const groupedFields = useMemo(() => {
    if (!result) return [];
    const byGroup = new Map<string, string[]>();
    for (const field of result.table.fields) {
      const group = FIELD_LABELS[field]?.group ?? "其他";
      byGroup.set(group, [...(byGroup.get(group) ?? []), field]);
    }
    return FIELD_GROUPS.filter((group) => byGroup.has(group)).map((group) => ({
      group,
      fields: byGroup.get(group)!,
    }));
  }, [result]);

  const openComparison = (comparisonId: string) => {
    fetch(`${API}/api/v1/comparisons/${comparisonId}`)
      .then((response) => response.json())
      .then((data) => {
        setResult(data);
        setRunning(null);
        setQaMessages([]);
      })
      .catch(() => undefined);
    setShowHistory(false);
  };

  return (
    <main className="flex-1 overflow-y-auto bg-[#f7f7f5]">
      <div className="max-w-[1100px] mx-auto px-8 py-8">
        {/* 头部 */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-[#202124]">多篇论文比较</h1>
            <p className="mt-1 text-sm text-[#6b7280]">
              各篇独立证据化抽取 → 可比性判定 → 对比矩阵；引文可核实、可跳原文。
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowHistory((open) => !open)}
              className="text-sm text-[#2f4b7c] hover:underline"
            >
              {showHistory ? "隐藏历史" : "比较历史"}
            </button>
            <Link href="/" className="text-sm text-[#2f4b7c] hover:underline">
              ← 返回
            </Link>
          </div>
        </div>

        {/* 历史 */}
        {showHistory && (
          <div className="mt-4 rounded-xl border border-[#e6e7ea] bg-white p-3 shadow-sm">
            <p className="text-xs font-medium text-[#3d4451] mb-2">最近比较</p>
            {history.length === 0 && <p className="text-xs text-[#9aa0a6]">暂无历史。</p>}
            {history.map((item) => (
              <button
                key={String(item.comparison_id)}
                onClick={() => openComparison(String(item.comparison_id))}
                className="flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-[#f0f4f8]"
              >
                <span className="text-xs text-[#3d4451]">
                  {(item.paper_version_ids as string[]).map(titleFor).join(" vs ").slice(0, 60)}
                </span>
                <span className="text-[10px] text-[#9aa0a6]">{String(item.alignment ?? item.status)}</span>
                <span className="ml-auto text-[10px] text-[#9aa0a6]">
                  {String(item.created_at).slice(5, 16)}
                </span>
              </button>
            ))}
          </div>
        )}

        {/* 添加论文：上传/arXiv 导入（与首页同管线，完成后自动选中） */}
        <div className="mt-6 rounded-xl border border-[#e6e7ea] bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-[#3d4451]">添加论文</p>
            <button
              onClick={() => setAddOpen((open) => !open)}
              className="text-xs text-[#2f4b7c] hover:underline"
            >
              {addOpen ? "收起" : "展开"}
            </button>
          </div>
          {addOpen && (
            <div className="mt-3 space-y-3">
              <div
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
                onClick={() => document.getElementById("compare-file-input")?.click()}
                className={`flex cursor-pointer items-center justify-center rounded-lg border-2 border-dashed px-4 py-5 text-sm text-[#6b7280] transition-colors ${
                  dragOver ? "border-[#2f4b7c] bg-[#f0f4f8]" : "border-[#dbe3ee] hover:border-[#2f4b7c]/50"
                }`}
              >
                拖拽 PDF 到此处，或点击选择文件
              </div>
              <input
                id="compare-file-input"
                type="file"
                accept="application/pdf"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void upload(file);
                  event.target.value = "";
                }}
              />
              <div className="flex gap-2">
                <input
                  value={arxivInput}
                  onChange={(event) => setArxivInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void importArxiv();
                  }}
                  placeholder="arXiv 编号（如 1706.03762）"
                  className="flex-1 rounded-lg border border-[#e6e7ea] px-3 py-2 text-sm focus:outline-none focus:border-[#2f4b7c]"
                />
                <button
                  onClick={() => void importArxiv()}
                  disabled={!arxivInput.trim()}
                  className="rounded-lg border border-[#2f4b7c] px-4 py-2 text-sm text-[#2f4b7c] hover:bg-[#f0f4f8] disabled:opacity-40"
                >
                  arXiv 导入
                </button>
              </div>
              {jobStatus && (
                <div className="rounded-lg bg-[#f0f4f8] p-3">
                  <div className="flex items-center gap-2">
                    <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-[#2f4b7c]" />
                    <span className="text-xs text-[#2f4b7c]">{jobStatus}</span>
                    {jobProgress > 0 && (
                      <span className="ml-auto text-xs text-[#9aa0a6]">
                        {Math.round(jobProgress * 100)}%
                      </span>
                    )}
                  </div>
                  {jobProgress > 0 && jobProgress < 1 && (
                    <div className="mt-2 h-1.5 rounded-full bg-[#dbe3ee]">
                      <div
                        className="h-1.5 rounded-full bg-[#2f4b7c] transition-all"
                        style={{ width: `${Math.round(jobProgress * 100)}%` }}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* 选论文 */}
        <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {papers.map((paper) => {
            const active = selected.includes(paper.paper_id);
            return (
              <button
                key={paper.paper_id}
                onClick={() => {
                  if (running) return;
                  setSelected((list) => {
                    if (list.includes(paper.paper_id)) return list.filter((id) => id !== paper.paper_id);
                    if (list.length >= 3) {
                      setError("最多选择 3 篇论文");
                      return list;
                    }
                    setError("");
                    return [...list, paper.paper_id];
                  });
                }}
                className={`rounded-xl border p-3 text-left transition-all ${
                  active
                    ? "border-[#2f4b7c] bg-white shadow-sm ring-1 ring-[#2f4b7c]/30"
                    : "border-[#e6e7ea] bg-white hover:border-[#2f4b7c]/50"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium text-[#202124] line-clamp-2">{paper.title}</p>
                  {active && (
                    <span className="shrink-0 rounded-full bg-[#2f4b7c] px-2 py-0.5 text-[10px] text-white">
                      ✓ 已选
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-[#9aa0a6]">
                  {paper.source} · {paper.version_id?.slice(0, 10)}
                </p>
              </button>
            );
          })}
        </div>

        {/* 操作区 */}
        <div className="mt-5 flex items-center gap-3">
          <button
            onClick={async () => {
              if (selected.length < 2 || running) return;
              setError("");
              setResult(null);
              setQaMessages([]);
              const versionIds = papers
                .filter((paper) => selected.includes(paper.paper_id))
                .map((paper) => paper.version_id ?? paper.paper_id);
              try {
                const response = await fetch(`${API}/api/v1/comparisons`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ paper_version_ids: versionIds }),
                });
                if (!response.ok) throw new Error(`比较启动失败（${response.status}）`);
                setRunning((await response.json()) as ComparisonResult);
              } catch (err) {
                setError(String(err));
              }
            }}
            disabled={selected.length < 2 || !!running}
            className="rounded-lg bg-[#2f4b7c] px-5 py-2.5 text-sm text-white shadow-sm hover:bg-[#263d64] disabled:opacity-40"
          >
            {running ? "比较运行中…" : `开始比较 ${selected.length} 篇`}
          </button>
          <span className="text-xs text-[#9aa0a6]">已选 {selected.length}/3</span>
          {result && (
            <button onClick={() => void exportMarkdown()} className="text-sm text-[#2f4b7c] hover:underline">
              导出 Markdown
            </button>
          )}
        </div>
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

        {/* 2026-08-07（教师优化 2）：已选论文概览大卡片——标题 + 摘要简介，
            让用户清楚在比较什么论文 */}
        {selectedPapers.length > 0 && (
          <div className="mt-5">
            <p className="text-xs font-medium text-[#9aa0a6] mb-2">
              已选论文（{selectedPapers.length}/3）
            </p>
            <div className="grid gap-3 md:grid-cols-3">
              {selectedPapers.map((paper) => {
                const meta = paperMeta[paper.paper_id];
                return (
                  <div
                    key={paper.paper_id}
                    className="rounded-xl border border-[#e6e7ea] bg-white p-4 shadow-sm"
                  >
                    <p className="text-sm font-medium text-[#202124] leading-snug line-clamp-2">
                      {paper.title}
                    </p>
                    <p className="mt-1 text-[10px] text-[#9aa0a6]">
                      {paper.source} · {paper.version_id?.slice(0, 10)}
                    </p>
                    {meta?.abstract ? (
                      <p className="mt-2 text-xs leading-relaxed text-[#6b7280] line-clamp-3">
                        {meta.abstract}
                      </p>
                    ) : (
                      <p className="mt-2 text-xs text-[#9aa0a6]">摘要加载中…</p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* 运行进度 */}
        {running && (
          <div className="mt-4 rounded-xl border border-[#2f4b7c]/30 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-[#2f4b7c]" />
              <span className="text-sm text-[#2f4b7c]">{running.stage ?? "正在准备…"}</span>
              <span className="ml-auto text-xs text-[#9aa0a6]">
                {Math.round((running.progress ?? 0) * 100)}%
              </span>
            </div>
            <div className="mt-2 h-1.5 rounded-full bg-[#dbe3ee]">
              <div
                className="h-1.5 rounded-full bg-[#2f4b7c] transition-all"
                style={{ width: `${Math.round((running.progress ?? 0) * 100)}%` }}
              />
            </div>
          </div>
        )}

        {/* 结果 */}
        {result && result.status === "DONE" && (
          <div className="mt-8 space-y-6">
            {/* 对齐判定 */}
            <div className="rounded-xl border border-[#e6e7ea] bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-center gap-3">
                <span
                  className={`inline-block rounded-full border px-4 py-1.5 text-sm font-medium ${
                    (ALIGNMENT_BADGE[result.alignment.alignment] ?? { cls: "" }).cls
                  }`}
                >
                  {ALIGNMENT_BADGE[result.alignment.alignment]?.label ?? result.alignment.alignment}
                  {typeof result.alignment.confidence === "number"
                    ? ` · 置信度 ${Math.round(result.alignment.confidence * 100)}%`
                    : ""}
                  {result.cached ? " · 已缓存" : ""}
                </span>
                <span className="text-xs text-[#6b7280] max-w-2xl leading-relaxed">
                  {result.alignment.rationale}
                </span>
              </div>
              {result.table.warnings.length > 0 && (
                <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700">
                  {result.table.warnings.map((warning, index) => (
                    <p key={index}>⚠ {warning}</p>
                  ))}
                </div>
              )}
            </div>

            {/* 对比矩阵（按组） */}
            <div className="space-y-6">
              {groupedFields.map(({ group, fields }) => (
                <div key={group}>
                  <h2 className="mb-2 text-sm font-medium text-[#3d4451]">{group}</h2>
                  <div className="overflow-x-auto rounded-xl border border-[#e6e7ea] bg-white shadow-sm">
                    <table className="w-full text-xs border-collapse">
                      <thead>
                        <tr className="bg-[#f7f8fa] text-left text-[#3d4451]">
                          <th className="px-3 py-2 w-40">字段</th>
                          {result.table.paper_ids.map((versionId) => (
                            <th key={versionId} className="px-3 py-2 min-w-[220px]">
                              <span className="font-medium">{titleFor(versionId)}</span>
                              <span className="ml-1.5 text-[10px] text-[#9aa0a6]">
                                {shortId(versionId)}
                              </span>
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {fields.map((field) => {
                          const meta = FIELD_LABELS[field] ?? { label: field, hint: "", group: "" };
                          return (
                            <tr key={field} className="border-t border-[#eceef1] align-top">
                              <td className="px-3 py-2.5">
                                <div className="font-medium text-[#3d4451]">{meta.label}</div>
                                {meta.hint && (
                                  <div className="mt-0.5 text-[10px] text-[#9aa0a6]">{meta.hint}</div>
                                )}
                              </td>
                              {result.table.paper_ids.map((versionId) => {
                                const cell = result.table.cells.find(
                                  (item) => item.paper_id === versionId && item.field === field
                                );
                                if (!cell) return <td key={versionId} className="px-3 py-2" />;
                                const status = CELL_STATUS[cell.status] ?? { label: "", cls: "" };
                                const expanded = expandedCells === `${versionId}-${field}`;
                                return (
                                  <td key={versionId} className="px-3 py-2.5">
                                    <div className="flex items-start gap-1.5">
                                      <span className={`mt-0.5 shrink-0 text-[10px] ${status.cls}`}>
                                        {status.label}
                                      </span>
                                      {cell.value ? (
                                        <button
                                          onClick={() => toggleCell(cell, versionId)}
                                          className={`text-left leading-relaxed text-[#202124] hover:text-[#2f4b7c] ${
                                            expanded ? "" : "line-clamp-3"
                                          }`}
                                          title="点击展开/收起（含证据引文与译文）"
                                        >
                                          {cell.value}
                                          {zhCell(cell, versionId) && (
                                            <span className="mt-0.5 block text-[11px] leading-relaxed text-[#5a6b8c]">
                                              {zhCell(cell, versionId)}
                                            </span>
                                          )}
                                        </button>
                                      ) : (
                                        <span className="text-[#9aa0a6]">{cell.note || "未找到"}</span>
                                      )}
                                    </div>
                                    {expanded && (
                                      <div className="mt-2 space-y-2 rounded-lg bg-[#f7f8fa] p-2.5">
                                        {cell.quotes.length === 0 && (
                                          <p className="text-[11px] text-[#9aa0a6]">暂无证据引文。</p>
                                        )}
                                        {cell.quotes.map((quote, index) => {
                                          const blockIds = cell.locators[index]?.block_ids ?? [];
                                          const translated = translatedQuote(
                                            paperIdFor(versionId),
                                            blockIds
                                          );
                                          return (
                                            <div key={index}>
                                              <p className="text-[11px] text-[#3d4451] leading-relaxed">
                                                “{quote.slice(0, 200)}”
                                              </p>
                                              {translated && (
                                                <p className="mt-0.5 text-[11px] text-[#2f4b7c] leading-relaxed">
                                                  {translated}
                                                </p>
                                              )}
                                            </div>
                                          );
                                        })}
                                        {cell.locators.length > 0 && (
                                          <Link
                                            href={`/paper/${paperIdFor(versionId)}?locate=${
                                              cell.locators[0].block_ids[0] ?? ""
                                            }:${cell.locators[0].page}`}
                                            className="inline-block text-[11px] text-[#2f4b7c] hover:underline"
                                          >
                                            跳到论文第 {cell.locators[0].page} 页 →
                                          </Link>
                                        )}
                                      </div>
                                    )}
                                  </td>
                                );
                              })}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>

            {/* 数值结果对比 */}
            {result.result_comparisons.length > 0 && (
              <div>
                <h2 className="mb-2 text-sm font-medium text-[#3d4451]">数值结果对比</h2>
                <div className="overflow-x-auto rounded-xl border border-[#e6e7ea] bg-white shadow-sm">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="bg-[#f7f8fa] text-left text-[#3d4451]">
                        <th className="px-3 py-2">数据集</th>
                        <th className="px-3 py-2">指标</th>
                        {result.table.paper_ids.map((versionId) => (
                          <th key={versionId} className="px-3 py-2">{shortId(versionId)}</th>
                        ))}
                        <th className="px-3 py-2">可比性</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.result_comparisons.map((group, index) => (
                        <tr key={index} className="border-t border-[#eceef1]">
                          <td className="px-3 py-2 font-medium text-[#3d4451]">
                            {group.dataset || "—"}
                          </td>
                          <td className="px-3 py-2 text-[#6b7280]">{group.metric}</td>
                          {result.table.paper_ids.map((versionId) => {
                            const value = group.values[versionId];
                            // 审计 P0-7（2026-08-05）：自动"最佳值"判定不可靠
                            // （行识别/指标方向/条件通配），提交版不显示 ★
                            return (
                              <td key={versionId} className="px-3 py-2 text-[#202124]">
                                {value || "—"}
                              </td>
                            );
                          })}
                          <td className="px-3 py-2">
                            {group.same_key ? (
                              <span
                                className="text-emerald-600"
                                title="数据集/指标/条件一致，数值可直接对比（不自动判定谁优）"
                              >
                                同条件可对比
                              </span>
                            ) : (
                              <span
                                className="text-amber-600"
                                title="各论文条件不一致，不宜直接比较数值"
                              >
                                Not directly comparable
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* 对话式问答 */}
            <div>
              <h2 className="mb-2 text-sm font-medium text-[#3d4451]">比较问答</h2>
              <div className="rounded-xl border border-[#e6e7ea] bg-white shadow-sm">
                <div className="flex h-72 flex-col overflow-y-auto p-4">
                  {qaMessages.length === 0 && (
                    <div className="flex flex-1 items-center justify-center">
                      <p className="text-xs text-[#9aa0a6]">
                        例如：两篇论文的方法核心区别是什么？哪个更值得复现？
                      </p>
                    </div>
                  )}
                  {qaMessages.map((message, index) => (
                    <div
                      key={index}
                      className={`mb-3 max-w-[85%] ${message.role === "user" ? "self-end" : "self-start"}`}
                    >
                      <div
                        className={`rounded-xl px-3.5 py-2.5 text-sm leading-relaxed ${
                          message.role === "user"
                            ? "bg-[#2f4b7c] text-white"
                            : "bg-[#f0f2f5] text-[#202124]"
                        }`}
                      >
                        {message.content}
                      </div>
                      {message.role === "assistant" &&
                        message.paperEvidence &&
                        Object.keys(message.paperEvidence).length > 0 && (
                          <div className="mt-1.5 space-y-1">
                            {Object.entries(message.paperEvidence).map(([paperId, quotes]) =>
                              quotes.slice(0, 2).map((quote, quoteIndex) => (
                                <p key={`${paperId}-${quoteIndex}`} className="text-[11px] text-[#6b7280]">
                                  [{shortId(paperId)}] “{quote.slice(0, 120)}”
                                </p>
                              ))
                            )}
                          </div>
                        )}
                      {message.role === "assistant" && message.comparability && (
                        <p className="mt-1 text-[10px] text-[#9aa0a6]">
                          可比性：{message.comparability}
                        </p>
                      )}
                    </div>
                  ))}
                  {qaBusy && (
                    <div className="self-start rounded-xl bg-[#f0f2f5] px-3.5 py-2.5 text-sm text-[#9aa0a6]">
                      正在回答…
                    </div>
                  )}
                </div>
                <div className="flex gap-2 border-t border-[#e6e7ea] p-3">
                  <input
                    value={qaInput}
                    onChange={(event) => setQaInput(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void askQuestion();
                    }}
                    placeholder="追问：条件不一致时结论可信吗？"
                    className="flex-1 rounded-lg border border-[#e6e7ea] px-3 py-2 text-sm focus:outline-none focus:border-[#2f4b7c]"
                  />
                  <button
                    onClick={() => void askQuestion()}
                    disabled={qaBusy || !qaInput.trim()}
                    className="rounded-lg bg-[#2f4b7c] px-4 py-2 text-sm text-white hover:bg-[#263d64] disabled:opacity-40"
                  >
                    发送
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
