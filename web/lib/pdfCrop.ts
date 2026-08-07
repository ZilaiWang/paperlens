// Client-side PDF page crop (改进方案1.md §11.2): the PDF.js canvas is the
// rasterizer, so no server-side poppler/PyMuPDF dependency is needed. The
// crop is exported as PNG for the "download figure/table" feature.
//
// pdfjs-dist is loaded dynamically so the module never executes during SSR
// (it requires browser APIs like DOMMatrix).

// PDF 文档复用缓存（V3.9）：每次裁剪都重新下载+解析整份 PDF 是"下载慢"
// 的主因；同一论文多次下载只解析一次。
const pdfCache = new Map<string, Promise<unknown>>();

function getCachedPdf(pdfjs: unknown, pdfUrl: string) {
  const cached = pdfCache.get(pdfUrl);
  if (cached) return cached;
  const promise = (pdfjs as { getDocument: (opts: { url: string }) => { promise: Promise<unknown> } })
    .getDocument({ url: pdfUrl }).promise;
  pdfCache.set(pdfUrl, promise);
  return promise;
}

export async function cropPagePng(
  pdfUrl: string,
  pageNumber: number,
  bbox: number[],
  scale = 2
): Promise<string> {
  const pdfjs = await import("pdfjs-dist");
  // The worker is copied to public/pdf.worker.mjs (Turbopack does not support
  // ?url imports of the mjs worker in this Next version).
  pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.mjs";
  const pdf = (await getCachedPdf(pdfjs, pdfUrl)) as {
    getPage: (n: number) => Promise<{
      getViewport: (opts: { scale: number }) => { width: number; height: number };
      render: (opts: { canvas: HTMLCanvasElement; viewport: unknown }) => { promise: Promise<void> };
    }>;
    cleanup: () => Promise<void>;
  };
  const page = await pdf.getPage(pageNumber);
  const viewport = page.getViewport({ scale });
  const canvas = document.createElement("canvas");
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("canvas unavailable");
  await page.render({ canvas, viewport }).promise;

  const [x0, y0, x1, y1] = bbox;
  const cropCanvas = document.createElement("canvas");
  cropCanvas.width = Math.max(1, Math.round((x1 - x0) * scale));
  cropCanvas.height = Math.max(1, Math.round((y1 - y0) * scale));
  const cropContext = cropCanvas.getContext("2d");
  if (!cropContext) throw new Error("canvas unavailable");
  cropContext.drawImage(
    canvas,
    x0 * scale,
    y0 * scale,
    (x1 - x0) * scale,
    (y1 - y0) * scale,
    0,
    0,
    cropCanvas.width,
    cropCanvas.height
  );
  await pdf.cleanup();
  return cropCanvas.toDataURL("image/png");
}

export function downloadDataUrl(dataUrl: string, fileName: string): void {
  const link = document.createElement("a");
  link.href = dataUrl;
  link.download = fileName;
  link.click();
}
