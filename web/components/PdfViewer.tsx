"use client";

// 原版 PDF 阅读器：pdfjs-dist 逐页渲染 canvas，
// 证据定位以 bbox overlay 高亮，替代无法程序化高亮的 iframe。
// pdfjs-dist 动态导入避免 SSR 期执行（与 lib/pdfCrop.ts 同一模式）。

import { useCallback, useEffect, useRef, useState } from "react";

const SCALE = 1.4; // 基准；实际缩放随容器宽度自适应
const MAX_SCALE = 4.0; // 手动放大的上限

export interface PdfJumpTarget {
  key: number;
  page: number;
  bboxes: number[][];
}

interface RenderedPage {
  pageNumber: number;
  canvas: HTMLCanvasElement;
  cssWidth: number;  // CSS 像素（显示尺寸）
  cssHeight: number;
}

// V4.7c：renderPage 把 PDF 渲染进游离 canvas（document.createElement），
// 需要挂载组件把它接进 React 树——此前 JSX 渲染的是另一张空白 canvas，
// 原版模式永远空白（裁剪走 toDataURL 不受影响，故一直没暴露）
// V4.7e：canvas 位图像素 = CSS 尺寸 × devicePixelRatio（Retina 清晰），
// 显示尺寸由 cssWidth/cssHeight 控制
function MountedCanvas({
  canvas,
  cssWidth,
  cssHeight,
}: {
  canvas: HTMLCanvasElement;
  cssWidth: number;
  cssHeight: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    canvas.style.width = `${cssWidth}px`;
    canvas.style.height = `${cssHeight}px`;
    canvas.style.display = "block";
    node.appendChild(canvas);
    return () => {
      if (canvas.parentNode === node) node.removeChild(canvas);
    };
  }, [canvas, cssWidth, cssHeight]);
  return <div ref={ref} style={{ width: "100%", height: "100%" }} />;
}

export function PdfViewer({
  pdfUrl,
  pageCount,
  jumpTarget,
  onPageVisible,
}: {
  pdfUrl: string;
  pageCount: number;
  jumpTarget?: PdfJumpTarget | null;
  onPageVisible?: (page: number) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [rendered, setRendered] = useState<Map<number, RenderedPage>>(new Map());
  const [visiblePages, setVisiblePages] = useState<number[]>([]);
  const [overlay, setOverlay] = useState<{ key: number; page: number; bboxes: number[][]; scale: number } | null>(null);
  // pdfjs-dist v6 ships its own proxy types with a changed render API
  // (RenderParameters requires `canvas`); type the ref loosely so we stay
  // decoupled from exact shapes
  const pdfRef = useRef<any>(null);
  const renderedRef = useRef<Map<number, RenderedPage>>(new Map());
  renderedRef.current = rendered;
  const scaleRef = useRef(SCALE);
  // V4.7d：自适应缩放——PDF 页面宽度 = 左右栏之间的中央区宽度
  const [viewerWidth, setViewerWidth] = useState(612 * SCALE);
  // V4.7e：手动缩放（null = 适应宽度；数值 = 固定缩放，可放大）
  const [zoom, setZoom] = useState<number | null>(null);
  const zoomRef = useRef<number | null>(null);
  zoomRef.current = zoom;

  const adaptiveScale = Math.min(2.0, Math.max(0.8, viewerWidth / 612));
  const scale = zoom ?? adaptiveScale;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver(() => {
      const width = container.clientWidth - 1;
      if (width > 0) setViewerWidth(width);
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // 缩放（适应宽度 / 手动）变化 → 清空重渲染 + 槽位高度重算
  useEffect(() => {
    scaleRef.current = scale;
    setRendered(new Map());
    void pdfRef.current
      ?.getPage(1)
      .then((first: { getViewport: (opts: { scale: number }) => { height: number } }) =>
        setSlotHeight(first.getViewport({ scale: scaleRef.current }).height)
      )
      .catch(() => undefined);
  }, [scale]);

  // page geometry: PDF pages may differ in size; use the first page as the
  // scroll slot basis (Letter/A4 papers are uniform in practice)
  const [slotHeight, setSlotHeight] = useState(792 * SCALE);
  // HTML 论文的 blocks 只有 page 1（prop pageCount=1），原版模式必须用
  // PDF 的真实页数（V3.9）
  const [realPageCount, setRealPageCount] = useState(pageCount);
  const loadedUrlRef = useRef<string | null>(null);

  useEffect(() => {
    if (loadedUrlRef.current === pdfUrl) return; // 已加载过不再重载
    loadedUrlRef.current = pdfUrl;
    let cancelled = false;
    void (async () => {
      const pdfjs = await import("pdfjs-dist");
      pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.mjs";
      const pdf = await pdfjs.getDocument({ url: pdfUrl }).promise;
      if (cancelled) return;
      pdfRef.current = pdf;
      setRealPageCount(pdf.numPages || pageCount);
      const first = await pdf.getPage(1);
      const viewport = first.getViewport({ scale: scaleRef.current });
      setSlotHeight(viewport.height);
      // render the first pages immediately
      for (const pageNumber of [1, 2]) {
        void renderPage(pageNumber);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdfUrl]);

  const renderPage = useCallback(async (pageNumber: number) => {
    const pdf = pdfRef.current;
    if (!pdf || pageNumber < 1 || pageNumber > realPageCount) return;
    if (renderedRef.current.has(pageNumber)) return;
    try {
      const page = await pdf.getPage(pageNumber);
      // V4.7e：位图像素 = 缩放 × devicePixelRatio（Retina 2x 屏上不糊），
      // CSS 显示尺寸 = 位图像素 / DPR
      const dpr = window.devicePixelRatio || 1;
      const viewport = page.getViewport({ scale: scaleRef.current * dpr });
      const canvas = document.createElement("canvas");
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      // pdfjs-dist v6 RenderParameters: { canvas, viewport } (matches pdfCrop.ts)
      await page.render({ canvas, viewport }).promise;
      setRendered((previous) => {
        const map = new Map(previous);
        map.set(pageNumber, {
          pageNumber,
          canvas,
          cssWidth: viewport.width / dpr,
          cssHeight: viewport.height / dpr,
        });
        return map;
      });
    } catch {
      /* transient render failure: leave the slot blank */
    }
  }, [realPageCount]);

  // virtualize: render only the visible page plus one neighbour on each side
  const updateVisible = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const first = Math.max(1, Math.floor(container.scrollTop / slotHeight) + 1);
    const last = Math.min(realPageCount, Math.ceil((container.scrollTop + container.clientHeight) / slotHeight) + 1);
    const pages: number[] = [];
    for (let page = first; page <= last; page += 1) pages.push(page);
    setVisiblePages((previous) =>
      previous.length === pages.length && previous.every((page, index) => page === pages[index])
        ? previous
        : pages
    );
    onPageVisible?.(first);
  }, [slotHeight, realPageCount, onPageVisible]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    updateVisible();
    let raf = 0;
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(updateVisible);
    };
    container.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      container.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(raf);
    };
  }, [updateVisible]);

  // render pages that just became visible
  useEffect(() => {
    for (const page of visiblePages) void renderPage(page);
  }, [visiblePages, renderPage]);

  // jump to evidence: scroll the page into view and flash the bbox overlay
  useEffect(() => {
    if (!jumpTarget) return;
    const container = containerRef.current;
    if (!container) return;
    const scale = scaleRef.current;
    setOverlay({
      key: jumpTarget.key,
      page: jumpTarget.page,
      bboxes: jumpTarget.bboxes,
      scale,
    });
    container.scrollTo({
      top: (jumpTarget.page - 1) * slotHeight,
      behavior: "smooth",
    });
    window.setTimeout(() => setOverlay(null), 2000);
  }, [jumpTarget, slotHeight]);

  return (
    <div ref={containerRef} className="flex-1 overflow-auto bg-[#3d4451] relative">
      {/* V4.7e 缩放工具条：适应宽度 / 实际尺寸 / 放大缩小 */}
      <div className="sticky top-0 z-10 flex items-center gap-1 bg-[#3d4451]/90 px-3 py-1.5">
        <button
          onClick={() => setZoom(null)}
          className={`rounded px-2 py-0.5 text-xs ${zoom === null ? "bg-white/20 text-white" : "text-white/70 hover:bg-white/10"}`}
        >
          适应宽度
        </button>
        <button
          onClick={() => setZoom(1)}
          className={`rounded px-2 py-0.5 text-xs ${zoom === 1 ? "bg-white/20 text-white" : "text-white/70 hover:bg-white/10"}`}
        >
          100%
        </button>
        <span className="mx-1 text-white/30">|</span>
        <button
          onClick={() => setZoom((current) => Math.max(0.5, (current ?? adaptiveScale) - 0.2))}
          className="rounded px-2 py-0.5 text-xs text-white/70 hover:bg-white/10"
          title="缩小"
        >
          −
        </button>
        <span className="px-1 text-xs text-white/70">{Math.round(scale * 100)}%</span>
        <button
          onClick={() => setZoom((current) => Math.min(MAX_SCALE, (current ?? adaptiveScale) + 0.2))}
          className="rounded px-2 py-0.5 text-xs text-white/70 hover:bg-white/10"
          title="放大"
        >
          +
        </button>
      </div>
      <div className="mx-auto py-6" style={{ width: 612 * scale }}>
        {Array.from({ length: realPageCount }, (_, index) => index + 1).map((pageNumber) => {
          const page = rendered.get(pageNumber);
          const isOverlayPage = overlay?.page === pageNumber;
          return (
            <div
              key={pageNumber}
              className="mb-5 bg-white shadow-lg relative"
              style={{ width: page?.cssWidth ?? 612 * scale, height: page?.cssHeight ?? slotHeight }}
            >
              {page ? (
                <>
                  {/* V4.7c：挂载渲染好的 canvas（此前是空白 canvas） */}
                  <MountedCanvas
                    canvas={page.canvas}
                    cssWidth={page.cssWidth}
                    cssHeight={page.cssHeight}
                  />
                  {isOverlayPage && overlay && (
                    <div className="absolute inset-0 pointer-events-none">
                      {overlay.bboxes.map((bbox, index) => (
                        <div
                          key={`${overlay.key}-${index}`}
                          className="absolute pl-evidence flashing"
                          style={{
                            left: bbox[0] * overlay.scale,
                            top: bbox[1] * overlay.scale,
                            width: (bbox[2] - bbox[0]) * overlay.scale,
                            height: (bbox[3] - bbox[1]) * overlay.scale,
                          }}
                        />
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <div className="flex items-center justify-center h-full text-xs text-[#9aa0a6]">
                  第 {pageNumber} 页
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
