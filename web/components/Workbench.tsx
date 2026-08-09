"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import katex from "katex";
import { api, type AssetIR, type BlockIR, type PaperMeta, type ReferenceIR, type SectionIR } from "@/lib/api";
import { cropPagePng, downloadDataUrl } from "@/lib/pdfCrop";
import { AgentPanel } from "./AgentPanel";
import { AnalyticsPanel } from "./AnalyticsPanel";
import { PdfViewer, type PdfJumpTarget } from "./PdfViewer";

// V3.21 公式渲染：$...$ 行内 + FORMULA 块 display 模式。
// 后端（arxiv_html）用 $ 包裹行内 alttext；KaTeX 渲染失败回退原样文本。
const MATH_INLINE_RE = /\$([^$]+)\$/g;

/** 把文本里的 $...$ 段渲染为 KaTeX 行内公式，其余保持原样。 */
function renderMathSegments(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const re = new RegExp(MATH_INLINE_RE.source, "g");
  let last = 0;
  let index = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    try {
      nodes.push(
        <span
          key={`${keyPrefix}-m${index}`}
          dangerouslySetInnerHTML={{
            __html: katex.renderToString(match[1], { throwOnError: true }),
          }}
        />
      );
    } catch {
      nodes.push(match[0]); // 渲染失败 → 保留 $...$ 原文
    }
    last = match.index + match[0].length;
    index += 1;
  }
  if (last < text.length) nodes.push(text.slice(last));
  if (nodes.length === 0) nodes.push(text);
  return nodes;
}

/** FORMULA 块（display 公式）：KaTeX 居中渲染 + arXiv 风格右侧编号；失败回退原文。 */
function renderFormulaBlock(latexSource: string): { html: string } | null {
  try {
    return {
      html: katex.renderToString(latexSource, {
        displayMode: true,
        throwOnError: true,
      }),
    };
  } catch {
    return null;
  }
}
import type { EvidenceLocator } from "@/lib/api";

interface Callout {
  callout_id: string;
  block_id: string;
  char_start: number;
  char_end: number;
  raw: string;
  reference_id: string;
}

interface PageQualityItem {
  page: number;
  verdict: "GOOD" | "SUSPECT" | "LOW";
  fallback_reasons: string[];
  single_char_ratio: number;
  tiny_block_ratio: number;
  table_contamination: number;
}

type RailTab = "toc" | "figures" | "tables" | "references" | "analytics";

// V4.8（题目要求③）：参考文献格式问题中文文案
const REF_ISSUE_LABELS: Record<string, string> = {
  REF_MISSING_NUMBER: "缺少序号",
  REF_DUPLICATE_NUMBER: "序号重复",
  REF_NON_SEQUENTIAL_NUMBER: "序号不连续",
  REF_NON_IEEE_NUMBER: "序号格式非 IEEE（应为 [n]）",
  REF_MIXED_STYLE: "引用风格混用（数字式与作者-年份式并存）",
  REF_MISSING_AUTHOR: "缺少作者",
  REF_MISSING_TITLE: "缺少标题",
  REF_TITLE_TOO_SHORT: "标题过短，疑似解析不完整",
  REF_MISSING_YEAR: "缺少年份",
  REF_MISSING_FINAL_PERIOD: "末尾缺少句号",
  REF_BAD_DOI: "疑似 DOI 但未解析出",
  REF_BAD_ARXIV_ID: "疑似 arXiv 编号但未解析出",
};

const refIssueLabel = (issue: string) => {
  if (issue.startsWith("REF_IMPLAUSIBLE_YEAR")) {
    return `年份异常：${issue.split(":")[1]}`;
  }
  return REF_ISSUE_LABELS[issue] ?? issue;
};

type DisplayMode = "original" | "bilingual" | "chinese";

interface Translation {
  unit_id: string;
  source_block_ids: string[];
  target_text: string;
  status: string;
}

// 图内联缩略图：进入视口才裁剪，点击打开详情
function AssetThumb({
  pdfUrl,
  asset,
  onOpen,
}: {
  pdfUrl: string;
  asset: AssetIR;
  onOpen: (asset: AssetIR) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  // V3.23 图展示改走服务器代理端点：直链 arXiv URL 在用户浏览器不可达
  //（服务器才有 mihomo 代理 + 本地预下载缓存）；PDF 论文无 content_uri，
  // 进入视口后客户端裁剪
  const [src, setSrc] = useState<string | null>(
    asset.content_uri ? api.assetDownloadUrl(asset.asset_id) : null
  );

  useEffect(() => {
    if (src) return;
    const element = containerRef.current;
    if (!element) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting) return;
        observer.disconnect();
        void cropPagePng(pdfUrl, asset.page, asset.bbox, 1.2)
          .then(setSrc)
          .catch(() => undefined);
      },
      { rootMargin: "400px" }
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [pdfUrl, asset, src]);

  return (
    <div ref={containerRef} className="my-4">
      <button
        onClick={() => onOpen(asset)}
        className="block max-w-full rounded-lg border border-[#e6e7ea] bg-white p-1.5 hover:border-[#2f4b7c] transition-colors"
        aria-label={`查看 PDF 第 ${asset.page} 页的图`}
      >
        {src ? (
          <img src={src} alt="" className="max-h-72 mx-auto" />
        ) : (
          <div className="h-28 flex items-center justify-center text-xs text-[#9aa0a6]">
            p{asset.page} 图区域
          </div>
        )}
      </button>
    </div>
  );
}


export function Workbench({ paperId }: { paperId: string }) {
  const [sections, setSections] = useState<SectionIR[]>([]);
  const [blocks, setBlocks] = useState<BlockIR[]>([]);
  const [assets, setAssets] = useState<AssetIR[]>([]);
  const [references, setReferences] = useState<ReferenceIR[]>([]);
  const [mode, setMode] = useState<"immersive" | "pdf">("immersive");
  const [displayMode, setDisplayMode] = useState<DisplayMode>("bilingual");
  const [translations, setTranslations] = useState<Map<string, Translation>>(new Map());
  const [translatingPage, setTranslatingPage] = useState<string | null>(null);
  const [railTab, setRailTab] = useState<RailTab>("toc");
  // V4.8：参考文献格式过滤（全部 / 有问题的）
  const [refFilter, setRefFilter] = useState<"all" | "issues">("all");
  const [railOpen, setRailOpen] = useState(true);
  const [agentOpen, setAgentOpen] = useState(true);
  // 左右栏宽度（V3.18）：拖拽手柄调节，边界钳制
  const [railWidth, setRailWidth] = useState(240);
  const [agentWidth, setAgentWidth] = useState(420);
  // V4.3-1 上下文检索：滚动跟踪当前章节（供 Agent 限定检索范围）
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);

  useEffect(() => {
    const container = document.querySelector("[data-reader-scroll]");
    if (!container) return;
    const pick = () => {
      const rect = container.getBoundingClientRect();
      const top = rect.top + Math.min(240, rect.height * 0.3);
      let current: string | null = null;
      for (const heading of container.querySelectorAll("h2[id^='sec-']")) {
        if (heading.getBoundingClientRect().top <= top) current = heading.id.slice(4);
        else break;
      }
      setActiveSectionId(current);
    };
    container.addEventListener("scroll", pick, { passive: true });
    pick();
    return () => container.removeEventListener("scroll", pick);
  }, [blocks, mode]);

  const activeSectionBlocks = useMemo(() => {
    if (!activeSectionId) return [];
    return blocks
      .filter((block) => block.section_id === activeSectionId)
      .map((block) => block.block_id);
  }, [activeSectionId, blocks]);
  // HTML 论文无物理分页（所有章节 start_page 相同）——目录隐藏页码
  const hasRealPageNumbers = useMemo(
    () => new Set(sections.map((s) => s.start_page)).size > 1,
    [sections]
  );
  const [error, setError] = useState("");
  const [callouts, setCallouts] = useState<Callout[]>([]);
  // V3.18 拖拽调宽：window 级 pointermove 跟随，边界钳制；agent 是拖左缘
  // （右移 → 变窄），rail 拖右缘（右移 → 变宽）
  const beginResize = useCallback(
    (event: React.PointerEvent<HTMLDivElement>, which: "rail" | "agent") => {
      event.preventDefault();
      const startX = event.clientX;
      const startW = which === "rail" ? railWidth : agentWidth;
      const setW = which === "rail" ? setRailWidth : setAgentWidth;
      const [min, max] = which === "rail" ? [160, 480] : [280, 720];
      const onMove = (move: PointerEvent) => {
        const delta = move.clientX - startX;
        const next = which === "rail" ? startW + delta : startW - delta;
        setW(Math.min(max, Math.max(min, next)));
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    },
    [railWidth, agentWidth]
  );
  const [detail, setDetail] = useState<AssetIR | null>(null);
  const [cropping, setCropping] = useState(false);
  const [pendingPrompt, setPendingPrompt] = useState("");
  const [importingRef, setImportingRef] = useState<string | null>(null);
  const [importNotice, setImportNotice] = useState("");
  const [resolvingRef, setResolvingRef] = useState<string | null>(null);
  const [resolveAllState, setResolveAllState] = useState<{
    state: string;
    done: number;
    total: number;
    verified?: number;
    probable?: number;
    ambiguous?: number;
    unresolved?: number;
    error?: string;
  } | null>(null);
  const [meta, setMeta] = useState<PaperMeta | null>(null);
  const [pageQuality, setPageQuality] = useState<PageQualityItem[]>([]);
  const [qualityDismissed, setQualityDismissed] = useState(false);
  // 渐进阅读：视口进入触发翻译 + 预取下一页
  const [translatingPages, setTranslatingPages] = useState<Set<number>>(new Set());
  // 证据定位：沉浸模式高亮字符区间 / 原版模式 bbox overlay
  const [highlight, setHighlight] = useState<{
    key: number;
    blockId: string;
    charStart: number;
    charEnd: number;
  } | null>(null);
  const [pdfJump, setPdfJump] = useState<PdfJumpTarget | null>(null);
  // V4.7b：跨论文跳转定位（/paper/{id}?locate=blockId:page）
  const locateParam = useSearchParams().get("locate");

  // V4.7b：跨论文跳转定位（?locate=blockId:page）——blocks 就绪后
  // 滚动到目标块并整体高亮
  useEffect(() => {
    if (!locateParam || blocks.length === 0) return;
    const [blockId] = locateParam.split(":");
    if (!blockId) return;
    const block = blocks.find((item) => item.block_id === blockId);
    if (!block) return;
    setHighlight({
      key: Date.now(),
      blockId,
      charStart: 0,
      charEnd: Math.max(block.text.length - 1, 0),
    });
    window.setTimeout(() => {
      const element = document.querySelector(`[data-block="${blockId}"]`);
      element?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 300);
  }, [locateParam, blocks]);

  useEffect(() => {
    api
      .outline(paperId)
      .then((data) => setSections(data.sections))
      .catch((err) => setError(String(err)));
    api
      .document(paperId)
      .then((data) => setBlocks(data.blocks))
      .catch((err) => setError(String(err)));
    api
      .assets(paperId)
      .then(setAssets)
      .catch(() => setAssets([]));
    api
      .references(paperId)
      .then(setReferences)
      .catch(() => setReferences([]));
    api
      .callouts(paperId)
      .then(setCallouts)
      .catch(() => setCallouts([]));
    api
      .pageQuality(paperId)
      .then(setPageQuality)
      .catch(() => setPageQuality([]));
    api
      .meta(paperId)
      .then(setMeta)
      .catch(() => setMeta(null));
  }, [paperId]);

  const figures = useMemo(
    () => assets.filter((asset) => asset.asset_kind === "FIGURE"),
    [assets]
  );
  const tables = useMemo(
    () => assets.filter((asset) => asset.asset_kind === "TABLE"),
    [assets]
  );

  // 语义序渲染：caption 文本 → 资产映射，图内联插回
  const captionToAsset = useMemo(() => {
    const map = new Map<string, AssetIR>();
    for (const asset of assets) {
      const key = asset.caption_original.trim();
      if (key && !map.has(key)) map.set(key, asset);
    }
    return map;
  }, [assets]);

  // pdfUrl 稳定引用（V3.10）：api.pdfUrl 每次生成新字符串会让 PdfViewer
  // 反复取消并重载 PDF —— 后台翻译更新触发重渲染时原版模式空白
  const pdfUrlMemo = useMemo(() => api.pdfUrl(paperId), [paperId]);

  // 2026-08-06：进入论文页即后台预取原版 PDF（浏览器 HTTP 缓存，1 小时）——
  // 服务器带宽约 1Mbps、PDF 15MB，点"原版"再下载要等 2 分钟；预取后
  // pdf.js 命中缓存（配合 Range 分块）点击即显示
  useEffect(() => {
    const controller = new AbortController();
    void fetch(pdfUrlMemo, { signal: controller.signal })
      .then((response) => response.blob())
      .catch(() => undefined);
    return () => controller.abort();
  }, [pdfUrlMemo]);

  // 2026-08-07（教师优化 1）：解析时生成的示例问题 → Agent 输入框
  // placeholder 动态化；未生成时回退默认文案
  const [sampleQuestion, setSampleQuestion] = useState("");
  useEffect(() => {
    api
      .sampleQuestions(paperId)
      .then((data) => setSampleQuestion(data.questions[0] ?? ""))
      .catch(() => undefined);
  }, [paperId]);

  // group blocks per page for the immersive reader
  const pages = useMemo(() => {
    const map = new Map<number, BlockIR[]>();
    for (const block of blocks) {
      const list = map.get(block.page) ?? [];
      list.push(block);
      map.set(block.page, list);
    }
    return [...map.entries()].sort((a, b) => a[0] - b[0]);
  }, [blocks]);

  // V3.18 摘要去重：HTML 摘要 block（metadata.html_section=Abstract）不再在
  // 正文流重复渲染（论文头白圆框展示英文 + 译文）；译文来自该 block 的翻译
  // 单元（预翻译前 15 段已含摘要，V3.12 按段落序取）
  const abstractTranslation = useMemo(() => {
    const abstractBlock = blocks.find(
      (block) =>
        (block.metadata as { html_section?: string }).html_section === "Abstract" &&
        block.block_type === "TEXT"
    );
    return abstractBlock ? translations.get(abstractBlock.block_id) : undefined;
  }, [blocks, translations]);

  const scrollToSection = useCallback((section: SectionIR) => {
    const heading = document.getElementById(`sec-${section.section_id}`);
    heading?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const loadTranslations = useCallback(
    (page: number) => {
      api
        .translations(paperId, page)
        .then((units) => {
          // functional update: consecutive calls in a background loop must
          // not clobber each other's entries (closure over a stale Map)
          setTranslations((previous) => {
            const map = new Map(previous);
            for (const unit of units) {
              if (unit.source_block_ids[0]) map.set(unit.source_block_ids[0], unit);
            }
            return map;
          });
        })
        .catch(() => undefined);
    },
    [paperId]
  );

  const translatePages = useCallback(
    async (pages: number[], loadPages?: number[]) => {
      if (translatingPage !== null) return;
      setTranslatingPage(`翻译中：第 ${pages[0]}${pages.length > 1 ? `-${pages[pages.length - 1]} 页` : " 页"}…`);
      // V4.6-5（检查 4）：翻译逐条显示——翻译期间每 3 秒拉一次已完成译文，
      // 服务端按批次持久化，译文逐批出现而非全部完成后一次性显示
      const pagesToLoad = loadPages ?? pages;
      const poll = window.setInterval(() => {
        for (const page of pagesToLoad) loadTranslations(page);
      }, 3000);
      try {
        const result = await api.translate(paperId, pages);
        for (const page of pagesToLoad) loadTranslations(page);
        setTranslatingPage(
          result.cached > 0 && result.translated === 0 ? null : null
        );
      } catch (err) {
        setTranslatingPage(`翻译失败：${err instanceof Error ? err.message.slice(0, 40) : String(err)}`);
        setTimeout(() => setTranslatingPage(null), 4000);
        return;
      } finally {
        window.clearInterval(poll);
        setTranslatingPage(null);
      }
    },
    [paperId, translatingPage, loadTranslations]
  );

  // Continuous background translation: the home page already translated the
  // first 5 pages; here we keep going page by page until the whole paper is
  // done, showing progress on the page header.
  const pageCount = useMemo(() => Math.max(...pages.map(([page]) => page), 1), [pages]);
  const [autoTranslate, setAutoTranslate] = useState(false);

  // 进入即加载 job 已翻译好的内容（此前只有 translate 请求后才拉取译文，
  // 导入完成跳转后一句译文都不显示 —— fix 2026-08-04）
  // 注意：blocks 是异步到达的，第一次 effect 时 pages 可能还是空数组，
  // 此时绝不能置 ref（否则 blocks 到达后永远不再加载 —— 二次修复）
  const initialLoadRef = useRef(false);
  useEffect(() => {
    if (initialLoadRef.current || pages.length === 0) return;
    initialLoadRef.current = true;
    for (const [page] of pages) loadTranslations(page);
  }, [pages, loadTranslations]);

  const translateAll = useCallback(
    async (pagesToTranslate: number[]) => {
      if (autoTranslate) return;
      setAutoTranslate(true);
      try {
        for (let index = 0; index < pagesToTranslate.length; index += 5) {
          const batch = pagesToTranslate.slice(index, index + 5);
          setTranslatingPage(
            pageCount === 1
              ? "正在翻译全文…"
              : `后台翻译中：第 ${batch[0]}-${batch[batch.length - 1]} 页 / 共 ${pageCount} 页…`
          );
          try {
            await api.translate(paperId, batch);
            for (const page of batch) loadTranslations(page);
          } catch {
            break; // a failed batch stops the background loop
          }
        }
      } finally {
        setAutoTranslate(false);
        setTranslatingPage(null);
      }
    },
    [autoTranslate, paperId, pageCount, loadTranslations]
  );

  // 渐进翻译：进入视口的页翻译本页 + 预取下一页（不再进页面就全量后台跑）
  const translateVisible = useCallback(
    (page: number) => {
      setTranslatingPages((previous) => {
        if (previous.has(page)) return previous;
        const next = new Set(previous);
        next.add(page);
        return next;
      });
      const targets = [page, page + 1].filter((item) => item <= pageCount);
      api
        .translate(paperId, targets)
        .then(() => {
          for (const item of targets) loadTranslations(item);
        })
        .catch(() => undefined)
        .finally(() => {
          setTranslatingPages((previous) => {
            const next = new Set(previous);
            next.delete(page);
            return next;
          });
        });
    },
    [paperId, pageCount, loadTranslations]
  );

  useEffect(() => {
    if (displayMode === "original") return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const page = Number((entry.target as HTMLElement).dataset.page);
          if (Number.isFinite(page) && page > 0) translateVisible(page);
        }
      },
      { rootMargin: "320px 0px" }
    );
    for (const section of document.querySelectorAll("[data-page]")) observer.observe(section);
    return () => observer.disconnect();
  }, [displayMode, pages.length, translateVisible]);

  // 进入后自动持续翻译剩余内容直到结束：
  // PDF 论文从第 4 页继续；HTML 论文没有物理页（pageCount=1），
  // translate(page 1) 会覆盖全部段落 —— 未翻译的自动补上（V3.7）
  useEffect(() => {
    if (displayMode === "original") return;
    if (pageCount > 3) {
      const rest = Array.from({ length: pageCount - 3 }, (_, index) => index + 4);
      void translateAll(rest);
    } else if (pageCount === 1) {
      void translateAll([1]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperId, pageCount, displayMode]);

  const referenceById = useMemo(() => {
    const map = new Map<string, ReferenceIR>();
    for (const reference of references) map.set(reference.reference_id, reference);
    return map;
  }, [references]);

  // Render a paragraph with inline [n] callouts as clickable reference links
  // and the active evidence highlight span merged into the same walk.
  const renderParagraph = useCallback(
    (text: string, blockId: string) => {
      const blockCallouts = callouts
        .filter((callout) => callout.block_id === blockId)
        .sort((a, b) => a.char_start - b.char_start);
      type Span = {
        start: number;
        end: number;
        kind: "callout" | "highlight";
        callout?: Callout;
      };
      const spans: Span[] = blockCallouts.map((callout) => ({
        start: callout.char_start,
        end: callout.char_end,
        kind: "callout",
        callout,
      }));
      if (highlight?.blockId === blockId) {
        spans.push({
          start: highlight.charStart,
          end: highlight.charEnd,
          kind: "highlight",
        });
      }
      if (spans.length === 0) return renderMathSegments(text, blockId);
      spans.sort((a, b) => a.start - b.start || b.end - a.end);
      const segments: React.ReactNode[] = [];
      let cursor = 0;
      for (const span of spans) {
        if (span.start > cursor) {
          segments.push(...renderMathSegments(text.slice(cursor, span.start), blockId));
        }
        if (span.kind === "highlight") {
          segments.push(
            <mark
              key={`hl-${highlight?.key}-${span.start}`}
              className="pl-evidence flashing"
            >
              {renderMathSegments(text.slice(span.start, span.end), blockId)}
            </mark>
          );
        } else if (span.callout) {
          const reference = referenceById.get(span.callout.reference_id);
          segments.push(
            <button
              key={span.callout.callout_id}
              className="text-[#2f4b7c] hover:underline font-medium align-baseline"
              title={
                reference
                  ? `[${reference.sequence_number}] ${reference.raw_text.slice(0, 160)}`
                  : span.callout.reference_id
              }
              onClick={() => {
                setRailTab("references");
                setRailOpen(true);
                const seq = reference?.sequence_number;
                if (seq) {
                  window.setTimeout(() => {
                    const el = document.getElementById(`ref-item-${seq}`);
                    el?.scrollIntoView({ behavior: "smooth", block: "center" });
                    el?.classList.add("ref-flash");
                    window.setTimeout(() => el?.classList.remove("ref-flash"), 1800);
                  }, 80);
                }
              }}
            >
              {span.callout.raw}
            </button>
          );
        }
        cursor = Math.max(cursor, span.end);
      }
      if (cursor < text.length) {
        segments.push(...renderMathSegments(text.slice(cursor), blockId));
      }
      return segments;
    },
    [callouts, referenceById, highlight]
  );

  // 证据反向定位：沉浸模式滚动 + 字符区间高亮，
  // 原版模式交给 PdfViewer 做 bbox overlay。
  const locateEvidence = useCallback(
    (locator: EvidenceLocator) => {
      if (mode === "pdf") {
        setPdfJump({
          key: Date.now(),
          page: locator.page,
          bboxes: locator.bboxes,
        });
        return;
      }
      setHighlight({
        key: Date.now(),
        blockId: locator.block_id,
        charStart: locator.block_char_start,
        charEnd: locator.block_char_end,
      });
      window.setTimeout(() => {
        const element = document.querySelector(`[data-block="${locator.block_id}"]`);
        element?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 60);
    },
    [mode]
  );

  const downloadAsset = useCallback(
    async (asset: AssetIR) => {
      if (cropping) return;
      setCropping(true);
      try {
        if (asset.content_uri) {
          // HTML 论文：图是直链，经服务器代理下载（浏览器无法跨域 fetch）
          const response = await fetch(api.assetDownloadUrl(asset.asset_id));
          if (!response.ok) throw new Error(`下载失败（${response.status}）`);
          const blob = await response.blob();
          downloadDataUrl(
            await new Promise<string>((resolve) => {
              const reader = new FileReader();
              reader.onloadend = () => resolve(String(reader.result));
              reader.readAsDataURL(blob);
            }),
            `${asset.asset_kind.toLowerCase()}-${asset.asset_id}.png`
          );
        } else {
          // 高清下载（V3.13）：scale 2 → 4，输出 ~2400px 宽
          const dataUrl = await cropPagePng(api.pdfUrl(paperId), asset.page, asset.bbox, 4);
          downloadDataUrl(dataUrl, `${asset.asset_kind.toLowerCase()}-p${asset.page}.png`);
        }
      } catch (err) {
        setImportNotice(`截图失败：${err instanceof Error ? err.message : String(err)}`);
      } finally {
        setCropping(false);
      }
    },
    [cropping, paperId]
  );

  const importReference = useCallback(
    async (referenceId: string) => {
      if (importingRef) return;
      setImportingRef(referenceId);
      setImportNotice("");
      try {
        const result = await api.importReference(referenceId);
        setImportNotice(
          result.status === "QUEUED"
            ? "已开始解析该参考论文，稍后可在首页打开。"
            : (result.message ?? result.error ?? "无法导入")
        );
      } catch (err) {
        setImportNotice(err instanceof Error ? err.message : "导入失败");
      } finally {
        setImportingRef(null);
      }
    },
    [importingRef]
  );

  // 在线身份核验（Crossref/arXiv 瀑布式匹配，）
  const resolveReference = useCallback(
    async (referenceId: string) => {
      if (resolvingRef) return;
      setResolvingRef(referenceId);
      setImportNotice("");
      try {
        const result = await api.resolveReference(referenceId);
        const statusText =
          result.identity_status === "VERIFIED"
            ? "身份已核验 (VERIFIED)"
            : result.identity_status === "PROBABLE"
              ? "身份基本确认 (PROBABLE)"
              : result.identity_status === "AMBIGUOUS"
                ? "身份存疑 (AMBIGUOUS)"
                : "未匹配到在线记录 (UNRESOLVED)";
        setImportNotice(`${statusText}${result.doi ? ` · DOI ${result.doi}` : ""}${result.arxiv_id ? ` · arXiv ${result.arxiv_id}` : ""}`);
        api
          .references(paperId)
          .then(setReferences)
          .catch(() => undefined);
      } catch (err) {
        setImportNotice(err instanceof Error ? err.message : "身份核验失败");
      } finally {
        setResolvingRef(null);
      }
    },
    [resolvingRef, paperId]
  );

  // 批量在线身份核验（V4.8）：后台线程执行，前端 2s 轮询进度；
  // 大论文（200+ 条无 ID 全模糊搜索）可达数分钟，必须可见进度
  const resolveAllReferences = useCallback(async () => {
    if (resolveAllState?.state === "running") return;
    setImportNotice("");
    try {
      const result = await api.resolveAllReferences(paperId);
      if (result.total === 0) {
        setImportNotice(result.message ?? "该论文还没有可核验的参考文献");
        return;
      }
      setResolveAllState({ state: "running", done: 0, total: result.total });
      const tick = async () => {
        try {
          const st = await api.resolveAllStatus(paperId);
          setResolveAllState(st);
          // 边核验边刷新列表（后端每 10 条持久化一次）
          api
            .references(paperId)
            .then(setReferences)
            .catch(() => undefined);
          if (st.state === "done") {
            setImportNotice(
              `全部核验完成：✓ ${st.verified ?? 0} · 基本确认 ${st.probable ?? 0} · 存疑 ${st.ambiguous ?? 0} · 未匹配 ${st.unresolved ?? 0}`
            );
          } else if (st.state === "error") {
            setImportNotice(st.error ?? "全部核验失败");
          } else {
            window.setTimeout(tick, 2000);
          }
        } catch {
          window.setTimeout(tick, 2000);
        }
      };
      window.setTimeout(tick, 2000);
    } catch (err) {
      setImportNotice(err instanceof Error ? err.message : "全部核验失败");
    }
  }, [paperId, resolveAllState?.state]);

  return (
    <div className="h-screen flex flex-col bg-[#f7f7f5]">
      {/* top bar */}
      <header className="h-14 shrink-0 flex items-center justify-between px-4 border-b border-[#e6e7ea] bg-white">
        <div className="flex items-center gap-4 min-w-0">
          <Link href="/" className="text-sm font-semibold whitespace-nowrap">
            ← 论文库
          </Link>
          <span className="text-sm font-medium truncate">{paperId.slice(0, 12)}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setRailOpen((value) => !value)}
            className="px-3 py-1.5 text-sm text-[#6b7280] hover:text-[#2f4b7c] rounded-lg hover:bg-[#f0f2f5]"
          >
            目录
          </button>
          {/* V4.7b：单篇 → 多篇比较入口（带当前论文预选） */}
          <Link
            href={`/compare?papers=${paperId}`}
            className="px-3 py-1.5 text-sm text-[#2f4b7c] hover:bg-[#f0f4f8] rounded-lg"
            title="把当前论文加入多篇比较"
          >
            加入比较
          </Link>
          <div className="flex rounded-lg border border-[#e6e7ea] overflow-hidden">
            <button
              onClick={() => setMode("immersive")}
              className={`px-3 py-1.5 text-sm ${
                mode === "immersive" ? "bg-[#2f4b7c] text-white" : "text-[#6b7280] hover:text-[#2f4b7c]"
              }`}
            >
              沉浸
            </button>
            <button
              onClick={() => setMode("pdf")}
              className={`px-3 py-1.5 text-sm ${
                mode === "pdf" ? "bg-[#2f4b7c] text-white" : "text-[#6b7280] hover:text-[#2f4b7c]"
              }`}
            >
              原版
            </button>
          </div>
          {mode === "immersive" && (
            <div className="flex rounded-lg border border-[#e6e7ea] overflow-hidden">
              {(
                [
                  ["original", "原文"],
                  ["bilingual", "双语"],
                  ["chinese", "中文"],
                ] as [DisplayMode, string][]
              ).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setDisplayMode(key)}
                  className={`px-2.5 py-1.5 text-xs ${
                    displayMode === key
                      ? "bg-[#2f4b7c] text-white"
                      : "text-[#6b7280] hover:text-[#2f4b7c]"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
          <button
            onClick={() => setAgentOpen((value) => !value)}
            className="px-3 py-1.5 text-sm text-[#6b7280] hover:text-[#2f4b7c] rounded-lg hover:bg-[#f0f2f5]"
          >
            Agent
          </button>
        </div>
      </header>

      {error && (
        <div className="px-4 py-2 text-sm text-red-600 bg-red-50 border-b border-red-100">
          {error}
        </div>
      )}

      {/* 解析质量门：低可信页面如实展示，不悄悄假装正确 */}
      {!qualityDismissed && pageQuality.some((item) => item.verdict !== "GOOD") && (
        <div className="px-4 py-2 text-sm text-amber-700 bg-amber-50 border-b border-amber-100 flex items-center gap-3">
          <span className="shrink-0">⚠</span>
          <span className="min-w-0 flex-1">
            部分页面版面解析可信度较低：
            {pageQuality
              .filter((item) => item.verdict !== "GOOD")
              .slice(0, 5)
              .map((item) => (
                <span key={item.page} title={item.fallback_reasons.join("; ")}>
                  第 {item.page} 页
                  {item.fallback_reasons.includes("TOO_MANY_TINY_BLOCKS")
                    ? "（碎片过多）"
                    : item.fallback_reasons.includes("TABLE_TEXT_IN_BODY")
                      ? "（表格文字混入正文）"
                      : ""}
                </span>
              ))
              .reduce<React.ReactNode[]>((nodes, node, index, array) => {
                if (index === 0) return [node];
                return [...nodes, "、", node];
              }, [])}
            {pageQuality.filter((item) => item.verdict !== "GOOD").length > 5 ? " 等" : ""}
            ，已按低可信处理。
          </span>
          <button
            onClick={() => setQualityDismissed(true)}
            className="shrink-0 text-amber-500 hover:text-amber-700"
            aria-label="关闭解析质量提示"
          >
            ✕
          </button>
        </div>
      )}

      {/* three columns */}
      <div className="flex-1 flex min-h-0">
        {/* left rail */}
        {railOpen && (
          <aside
            style={{ width: railWidth }}
            className="shrink-0 border-r border-[#e6e7ea] bg-white flex flex-col min-h-0"
          >
            <nav className="flex flex-wrap border-b border-[#e6e7ea] text-xs">
              {(
                [
                  ["toc", "目录"],
                  ["analytics", "分析"],
                  ["figures", "图"],
                  ["tables", "表"],
                  ["references", "参考文献"],
                ] as [RailTab, string][]
              ).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setRailTab(key)}
                  className={`px-2.5 py-2.5 border-b-2 whitespace-nowrap ${
                    railTab === key
                      ? "border-[#2f4b7c] text-[#2f4b7c] font-medium"
                      : "border-transparent text-[#6b7280] hover:text-[#202124]"
                  }`}
                >
                  {label}
                </button>
              ))}
            </nav>
            <div className="flex-1 overflow-y-auto p-2">
              {railTab === "toc" &&
                sections.map((section) => (
                  <button
                    key={section.section_id}
                    onClick={() => scrollToSection(section)}
                    className="w-full text-left px-2.5 py-1.5 rounded-lg text-sm hover:bg-[#f0f2f5] text-[#3d4451] flex gap-2"
                    style={{ paddingLeft: `${0.75 + (section.level - 1) * 1}rem` }}
                  >
                    {hasRealPageNumbers && (
                      <span className="text-[#9aa0a6] shrink-0">p{section.start_page}</span>
                    )}
                    <span className="truncate">
                      {section.title}
                      {section.confidence < 0.7 && (
                        <span title="低置信章节" className="ml-1 text-amber-500">
                          ⚠
                        </span>
                      )}
                    </span>
                  </button>
                ))}
              {railTab === "figures" && (
                <div className="grid grid-cols-2 gap-2 p-1">
                  {figures.map((figure) => (
                    <button
                      key={figure.asset_id}
                      onClick={() => setDetail(figure)}
                      className="aspect-[4/3] rounded-lg border border-[#e6e7ea] overflow-hidden bg-[#f7f7f5] text-left hover:border-[#2f4b7c]"
                      title={figure.caption_original.slice(0, 80)}
                    >
                      <div className="h-full w-full flex items-center justify-center text-xs text-[#9aa0a6] p-1">
                        {figure.caption_original.slice(0, 40) || `p${figure.page} 图区`}
                      </div>
                    </button>
                  ))}
                  {figures.length === 0 && (
                    <p className="col-span-2 text-xs text-[#9aa0a6] p-2">尚无图资源</p>
                  )}
                </div>
              )}
              {railTab === "tables" && (
                <div className="space-y-1.5 p-1">
                  {tables.map((table) => (
                    <button
                      key={table.asset_id}
                      onClick={() => setDetail(table)}
                      className="w-full text-left rounded-lg border border-[#e6e7ea] p-2 text-xs text-[#3d4451] hover:border-[#2f4b7c] transition-colors"
                    >
                      {table.caption_original.slice(0, 80) || `p${table.page} 表区`}
                      {table.structured_data && (
                        <span className="text-[#2f4b7c]"> · 结构化</span>
                      )}
                    </button>
                  ))}
                  {tables.length === 0 && (
                    <p className="text-xs text-[#9aa0a6] p-2">尚无表资源</p>
                  )}
                </div>
              )}
              {railTab === "references" && (
                <div className="p-1">
                  {/* 参考文献：自动提取 → 格式检查 → 在线核验 */}
                  <div className="mb-2 rounded-lg border border-[#e6e7ea] bg-white p-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-medium text-[#3d4451]">
                        参考文献
                      </span>
                      <span className="text-[10px] text-[#9aa0a6]">
                        自动提取 · 格式检查 · 在线核验
                      </span>
                    </div>
                    <div className="mt-1.5 flex items-center gap-2">
                      <button
                        onClick={() => setRefFilter("all")}
                        className={`rounded-full px-2.5 py-0.5 text-[11px] ${
                          refFilter === "all"
                            ? "bg-[#2f4b7c] text-white"
                            : "border border-[#dbe3ee] text-[#2f4b7c]"
                        }`}
                      >
                        全部 {references.length}
                      </button>
                      <button
                        onClick={() => setRefFilter("issues")}
                        className={`rounded-full px-2.5 py-0.5 text-[11px] ${
                          refFilter === "issues"
                            ? "bg-amber-500 text-white"
                            : "border border-amber-300 text-amber-600"
                        }`}
                      >
                        ⚠ 有问题的{" "}
                        {references.filter((item) => item.format_issues.length > 0).length}
                      </button>
                      <button
                        onClick={() => void resolveAllReferences()}
                        disabled={resolveAllState?.state === "running"}
                        className="ml-auto rounded-full border border-[#2f4b7c] px-2.5 py-0.5 text-[11px] text-[#2f4b7c] hover:bg-[#f0f2f5] disabled:opacity-50"
                        title="对全部条目调用 Crossref/arXiv 在线核验身份"
                      >
                        {resolveAllState?.state === "running"
                          ? `核验中 ${resolveAllState.done}/${resolveAllState.total}`
                          : "全部核验"}
                      </button>
                    </div>
                    <p className="mt-1.5 text-[10px] text-[#9aa0a6]">
                      格式合规{" "}
                      {references.filter((item) => item.format_issues.length === 0).length} 条
                      · 已核验{" "}
                      {references.filter((item) => item.identity_status === "VERIFIED").length} 条
                    </p>
                  </div>
                  <div className="space-y-1.5">
                  {references
                    .filter(
                      (reference) =>
                        refFilter === "all" || reference.format_issues.length > 0
                    )
                    .map((reference) => (
                    <div
                      key={reference.reference_id}
                      id={`ref-item-${reference.sequence_number}`}
                      className="rounded-lg border border-[#e6e7ea] p-2 text-xs text-[#3d4451]"
                    >
                      <div>
                        <span className="text-[#9aa0a6]">[{reference.sequence_number}]</span>{" "}
                        {reference.raw_text.slice(0, 110)}
                        {reference.format_issues.length > 0 ? (
                          <span
                            className="ml-1 inline-block rounded bg-amber-100 px-1 text-amber-600"
                            title={reference.format_issues.map(refIssueLabel).join("；")}
                          >
                            ⚠{reference.format_issues.length}
                          </span>
                        ) : (
                          <span className="ml-1 text-emerald-500" title="格式规范">
                            ✓
                          </span>
                        )}
                      </div>
                      {reference.format_issues.length > 0 && (
                        <div className="mt-1.5 rounded bg-amber-50 p-1.5 text-[10px] text-amber-700">
                          {reference.format_issues.slice(0, 4).map(refIssueLabel).join("；")}
                        </div>
                      )}
                      <div className="mt-1.5 flex items-center gap-2">
                        {reference.identity_status === "VERIFIED" ? (
                          <span className="text-emerald-600" title="已通过 Crossref/arXiv 在线核验">
                            ✓ 已核验
                          </span>
                        ) : (
                          <span
                            className={
                              reference.identity_status === "AMBIGUOUS"
                                ? "text-amber-600"
                                : reference.identity_status === "PROBABLE"
                                  ? "text-[#2f4b7c]"
                                  : "text-[#9aa0a6]"
                            }
                          >
                            {reference.identity_status} · {reference.year || "?"}
                          </span>
                        )}
                        {(reference.arxiv_id || reference.doi) && (
                          <button
                            onClick={() => void importReference(reference.reference_id)}
                            disabled={importingRef === reference.reference_id}
                            className="text-[#2f4b7c] hover:underline disabled:opacity-50"
                          >
                            {importingRef === reference.reference_id ? "导入中…" : "在 PaperLens 中解析"}
                          </button>
                        )}
                        {reference.identity_status !== "VERIFIED" && (
                          <button
                            onClick={() => void resolveReference(reference.reference_id)}
                            disabled={resolvingRef === reference.reference_id}
                            className="text-[#2f4b7c] hover:underline disabled:opacity-50"
                          >
                            {resolvingRef === reference.reference_id ? "核验中…" : "核验身份"}
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                  {references.length === 0 && (
                    <p className="text-xs text-[#9aa0a6] p-2">未解析到参考文献条目</p>
                  )}
                  {importNotice && (
                    <p className="text-xs text-[#2f4b7c] p-1">{importNotice}</p>
                  )}
                  </div>
                </div>
              )}
              {railTab === "analytics" && (
                // V4.4 单篇旗舰：方法图谱/实验记录/复现清单/主张图
                <AnalyticsPanel paperId={paperId} />
              )}
            </div>
          </aside>
        )}
        {railOpen && (
          // V3.18b 拖拽热区：w-7 + -mx-3.5 让命中区跨过分割线两侧
          //（外盒宽 0，不挤占布局），悬停中线高亮提示可拖
          <div
            onPointerDown={(event) => beginResize(event, "rail")}
            className="group relative z-10 -mx-3.5 flex w-7 shrink-0 cursor-col-resize touch-none items-center justify-center"
            title="拖动调节目录栏宽度"
          >
            <div className="w-[3px] self-stretch rounded-full bg-transparent transition-colors group-hover:bg-[#2f4b7c]" />
          </div>
        )}

        {/* center reader */}
        <main className="flex-1 min-w-0 overflow-y-auto bg-[#f7f7f5]" data-reader-scroll>
          {mode === "immersive" ? (
            <div className="max-w-[860px] mx-auto px-10 py-10">
              {/* arXiv 风格论文头（V3.6）：标题居中、作者行、摘要块 */}
              {meta && (meta.title || meta.authors || meta.abstract) && (
                <header className="mb-10 pb-8 border-b border-[#e6e7ea] text-center">
                  {meta.title && (
                    <h1 className="paper-serif text-[28px] leading-snug font-semibold text-[#202124]">
                      {meta.title}
                    </h1>
                  )}
                  {meta.authors && (
                    <p className="mt-4 text-[15px] text-[#3d4451]">{meta.authors}</p>
                  )}
                  {meta.abstract && (
                    <div className="mt-6 text-left bg-white rounded-xl border border-[#e6e7ea] px-6 py-5">
                      <div className="text-xs font-semibold text-[#9aa0a6] uppercase tracking-wide mb-2">
                        Abstract
                      </div>
                      {displayMode !== "chinese" && (
                        <p className="paper-serif text-[15px] leading-[1.85] text-[#202124]">
                          {meta.abstract}
                        </p>
                      )}
                      {displayMode !== "original" &&
                        abstractTranslation &&
                        abstractTranslation.status !== "NEEDS_RETRY" &&
                        abstractTranslation.target_text && (
                          <div className="translation-block mt-3">
                            {abstractTranslation.target_text}
                          </div>
                        )}
                    </div>
                  )}
                </header>
              )}
              {pages.map(([page, pageBlocks]) => (
                <section
                  key={page}
                  className="page-section mb-12"
                  data-page={page}
                  style={{ contentVisibility: "auto", containIntrinsicSize: "auto 600px" }}
                >
                  <div className="flex items-center justify-between text-xs text-[#9aa0a6] mb-4 border-b border-[#e6e7ea] pb-2">
                    <span>PDF 第 {page} 页</span>
                    {displayMode !== "original" && (
                      <button
                        onClick={() => void translatePages([page], [page])}
                        disabled={translatingPage !== null}
                        className="text-[#2f4b7c] hover:underline disabled:opacity-50"
                      >
                        {translatingPage ?? "翻译本页"}
                      </button>
                    )}
                  </div>
                  {pageBlocks.map((block) => {
                    // V3.18 摘要去重：HTML 摘要已在论文头白圆框展示（含译文），
                    // 正文流不再重复渲染；无 meta.abstract（元信息缺失）时
                    // 保留 block 兜底
                    if (
                      (block.metadata as { html_section?: string }).html_section ===
                        "Abstract" &&
                      meta?.abstract
                    ) {
                      return null;
                    }
                    const heading = sections.find(
                      (section) => section.section_id === block.section_id
                    );
                    const isHeading =
                      block.block_type === "TEXT" &&
                      heading &&
                      heading.title === block.text.trim();
                    if (isHeading) {
                      return (
                        <h2
                          key={block.block_id}
                          id={`sec-${heading.section_id}`}
                          className={`paper-serif font-semibold mt-10 mb-4 ${
                            heading.level === 1 ? "text-2xl" : "text-xl"
                          }`}
                        >
                          {block.text}
                        </h2>
                      );
                    }
                    // HTML 路径公式 block 的 block_type 是 TEXT，角色在
                    // metadata.html_role（add() 恒建 TEXT，fix 2026-08-04）
                    const isFormula =
                      block.block_type === "FORMULA" ||
                      (block.metadata as { html_role?: string }).html_role === "FORMULA";
                    if (isFormula) {
                      const formulaNumber =
                        typeof block.metadata?.formula_number === "string" &&
                        block.metadata.formula_number
                          ? block.metadata.formula_number
                          : "";
                      // PDF 路径公式块带 ⟦FORMULA p.x b.y⟧ 检索占位前缀，渲染前剥离；
                      // HTML 路径是 alttext LaTeX。KaTeX 失败回退原文本
                      const latexSource = block.text
                        .replace(/^⟦FORMULA[^\]]*⟧\s*/, "")
                        .replace(/^\$/, "")
                        .replace(/\$$/, "");
                      const rendered = renderFormulaBlock(latexSource);
                      return (
                        <div
                          key={block.block_id}
                          className="my-4 bg-white border border-[#e6e7ea] rounded-lg overflow-x-auto"
                        >
                          <div className="flex items-center min-h-[3.25rem] px-6 py-3">
                            {/* arXiv 风格：公式居中，编号右对齐 */}
                            <div className="flex-1 text-center paper-serif">
                              {rendered ? (
                                <span
                                  dangerouslySetInnerHTML={{ __html: rendered.html }}
                                />
                              ) : (
                                <span className="whitespace-pre-wrap text-[#3d4451]">
                                  {latexSource}
                                </span>
                              )}
                            </div>
                            {formulaNumber && (
                              <span className="w-10 shrink-0 text-right text-xs text-[#9aa0a6]">
                                ({formulaNumber})
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    }
                    // 语义序渲染：caption 与图内联插回正文流
                    if (block.block_type === "CAPTION") {
                      const asset = captionToAsset.get(block.text.trim());
                      return (
                        <div key={block.block_id} className="my-4">
                          {asset && (
                            <AssetThumb
                              pdfUrl={api.pdfUrl(paperId)}
                              asset={asset}
                              onOpen={setDetail}
                            />
                          )}
                          <p className="paper-serif text-[14px] leading-relaxed text-[#6b7280] text-center">
                            {block.text}
                          </p>
                        </div>
                      );
                    }
                    if (
                      block.block_type === "UNKNOWN_MEDIA" ||
                      block.block_type === "TABLE_ROW"
                    ) {
                      return (
                        <div
                          key={block.block_id}
                          className="my-4 h-24 rounded-lg border border-dashed border-[#d0d3d8] flex items-center justify-center text-xs text-[#9aa0a6]"
                        >
                          图/表区域（PDF 第 {block.page} 页）
                        </div>
                      );
                    }
                    if (block.block_type !== "TEXT") {
                      return null;
                    }
                    // PDF 论文的 caption 是普通 TEXT 块：匹配到资产时同样内联图
                    const captionAsset = captionToAsset.get(block.text.trim());
                    const inlineTableRows = captionAsset?.structured_data?.rows;
                    const translation = translations.get(block.block_id);
                    return (
                      <div key={block.block_id} className="group relative">
                        {captionAsset && captionAsset.asset_kind === "FIGURE" && (
                          <AssetThumb
                            pdfUrl={api.pdfUrl(paperId)}
                            asset={captionAsset}
                            onOpen={setDetail}
                          />
                        )}
                        {/* 表格内联（V3.12）：表格 caption 块是 TEXT 类型，
                            此前只渲染 AssetThumb（对表格是空白裁剪） */}
                        {captionAsset &&
                          captionAsset.asset_kind === "TABLE" &&
                          inlineTableRows &&
                          inlineTableRows.length > 0 && (
                            <button
                              onClick={() => setDetail(captionAsset)}
                              className="block w-full text-left rounded-lg border border-[#e6e7ea] bg-white p-2 hover:border-[#2f4b7c] transition-colors"
                            >
                              <div className="overflow-x-auto">
                                <table className="w-full text-[11px] border-collapse">
                                  <tbody>
                                    {inlineTableRows.slice(0, 8).map((row, rowIndex) => (
                                      <tr key={rowIndex} className={rowIndex === 0 ? "bg-[#f7f8fa]" : ""}>
                                        {row.slice(0, 6).map((cell, colIndex) => (
                                          <td
                                            key={colIndex}
                                            className={`border border-[#eceef1] px-1.5 py-1 ${
                                              rowIndex === 0
                                                ? "font-medium text-[#3d4451]"
                                                : "text-[#202124]"
                                            }`}
                                          >
                                            {cell || "\u00a0"}
                                          </td>
                                        ))}
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                              {inlineTableRows.length > 8 && (
                                <div className="text-center text-[10px] text-[#9aa0a6] pt-1">
                                  展开完整表格 + 下载 CSV →
                                </div>
                              )}
                            </button>
                          )}
                        {displayMode !== "chinese" && (
                          <p
                            className="paper-serif text-[16px] leading-[1.85] text-[#202124] mb-1.5 select-text"
                            data-block={block.block_id}
                          >
                            {renderParagraph(block.text, block.block_id)}
                          </p>
                        )}
                        {displayMode !== "original" && (
                          translation ? (
                            translation.status === "NEEDS_RETRY" ? (
                              <div className="translation-block text-[#9aa0a6] italic">
                                译文生成失败 · 点击上方"翻译本页"重试
                              </div>
                            ) : (
                              <div
                                className="translation-block"
                                title={`原文：${block.text.slice(0, 120)}`}
                              >
                                {/* V3.21：译文含 $...$ 公式标记（翻译保护还原），
                                    同样 KaTeX 渲染 */}
                                {renderMathSegments(
                                  translation.target_text,
                                  `${block.block_id}-t`
                                )}
                              </div>
                            )
                          ) : block.text.length > 40 ? (
                            <div className="translation-block text-[#9aa0a6] italic">
                              译文待生成 · p{block.page}
                            </div>
                          ) : null
                        )}
                      </div>
                    );
                  })}
                </section>
              ))}
            </div>
          ) : (
            <PdfViewer
              pdfUrl={pdfUrlMemo}
              pageCount={pageCount}
              jumpTarget={pdfJump}
            />
          )}
        </main>

        {/* right agent panel */}
        {agentOpen && (
          <>
            <div
              onPointerDown={(event) => beginResize(event, "agent")}
              className="group relative z-10 -mx-3.5 flex w-7 shrink-0 cursor-col-resize touch-none items-center justify-center"
              title="拖动调节 Agent 面板宽度"
            >
              <div className="w-[3px] self-stretch rounded-full bg-transparent transition-colors group-hover:bg-[#2f4b7c]" />
            </div>
            <AgentPanel
              paperId={paperId}
              onClose={() => setAgentOpen(false)}
              blocks={blocks}
              sections={sections}
              pendingPrompt={pendingPrompt}
              onPromptConsumed={() => setPendingPrompt("")}
              onLocateEvidence={locateEvidence}
              width={agentWidth}
              contextBlockIds={activeSectionBlocks}
              exampleQuestion={sampleQuestion}
            />
          </>
        )}
      </div>

      {/* asset detail modal */}
      {detail && (
        <div
          className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-8"
          onClick={() => setDetail(null)}
        >
          <div
            className="bg-white rounded-2xl max-w-3xl w-full max-h-[85vh] overflow-y-auto p-6"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <span className="text-sm font-medium">
                {detail.asset_kind === "FIGURE" ? "图" : "表"} · PDF 第 {detail.page} 页
              </span>
              <button onClick={() => setDetail(null)} className="text-[#9aa0a6] hover:text-[#202124]">
                ✕
              </button>
            </div>
            {detail.caption_original && (
              <p className="paper-serif text-sm text-[#3d4451] mb-4 leading-relaxed">
                {detail.caption_original}
              </p>
            )}
            {/* 结构化表格（V3.12）：cell matrix 渲染 + CSV 下载 */}
            {detail.structured_data && detail.structured_data.rows.length > 0 && (
              <div className="mb-4 overflow-x-auto rounded-lg border border-[#e6e7ea]">
                <table className="w-full text-xs border-collapse">
                  <tbody>
                    {detail.structured_data.rows.map((row, rowIndex) => (
                      <tr key={rowIndex} className={rowIndex === 0 ? "bg-[#f7f8fa]" : ""}>
                        {row.map((cell, colIndex) => (
                          <td
                            key={colIndex}
                            className={`border border-[#eceef1] px-2 py-1.5 align-top ${
                              rowIndex === 0 ? "font-medium text-[#3d4451]" : "text-[#202124]"
                            }`}
                          >
                            {cell || " "}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              {detail.structured_data?.csv && (
                <button
                  onClick={() => {
                    const blob = new Blob([detail.structured_data?.csv ?? ""], {
                      type: "text/csv;charset=utf-8",
                    });
                    downloadDataUrl(
                      URL.createObjectURL(blob),
                      `${detail.asset_kind.toLowerCase()}-${detail.asset_id}.csv`
                    );
                  }}
                  className="px-4 py-2 rounded-lg border border-[#2f4b7c] text-[#2f4b7c] text-sm hover:bg-[#f0f2f5]"
                >
                  下载 CSV
                </button>
              )}
              {detail.asset_kind === "FIGURE" && (
                <button
                  onClick={() => void downloadAsset(detail)}
                  disabled={cropping}
                  className="px-4 py-2 rounded-lg bg-[#2f4b7c] text-white text-sm hover:bg-[#263d64] disabled:opacity-50"
                >
                  {cropping ? "生成中…" : "下载 PNG"}
                </button>
              )}
              <button
                onClick={() => {
                  setPendingPrompt(
                    `解释这篇论文的${detail.asset_kind === "FIGURE" ? "图" : "表"}（PDF 第 ${detail.page} 页）：${detail.caption_original.slice(0, 200)}。说明图中各模块/各行含义。`
                  );
                  setAgentOpen(true);
                }}
                className="px-4 py-2 rounded-lg border border-[#2f4b7c] text-[#2f4b7c] text-sm hover:bg-[#f0f2f5]"
              >
                在 Agent 中解释
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
