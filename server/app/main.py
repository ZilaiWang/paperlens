"""PaperLens FastAPI application.

Long tasks return {job_id, status: QUEUED} immediately; progress and validated
Agent claims stream over SSE (/api/jobs/{id}/events).
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from paperlens_core.documents import (
    Annotation,
    Asset,
    Block,
    BlockType,
    Chunk,
    Section,
    TranslationStatus,
    TranslationUnit,
)
from paperlens_core.jobs import JobType
from paperlens_core.quality import QualityAgent
from paperlens_core.version import __version__

from .arxiv import download_pdf, normalize_arxiv_input
from .events import bus
from .jobs import JobExecutor, create_arxiv_html_job, create_parse_job, new_job
from .logging_config import setup_logging
from .repository import Repository, now_iso
from .schemas import (
    AnnotationRequest,
    ArxivImportRequest,
    ChatRequest,
    ComparisonQuestion,
    ComparisonRequest,
    RenameRequest,
    ResolveRequest,
    TranslateRequest,
)
from .services.comparisons import ARTIFACT_FIELD_MAP, translate_comparison_cells

app = FastAPI(title="PaperLens", version=__version__)

# 翻译全局并发上限（审计 P1，2026-08-05）：单请求内 4 并发批次，但多个
# 请求会叠加打 API——进程级信号量把全局翻译并发钳制在 4 批
_TRANSLATE_SEMAPHORE = threading.Semaphore(4)

# The browser workspace session is an HttpOnly cookie, so credentialed CORS
# must use explicit origins rather than a wildcard.
cors_origins = [
    item.strip()
    for item in os.environ.get(
        "PAPERLENS_CORS_ORIGINS",
        "http://127.0.0.1:3000,http://localhost:3000",
    ).split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = os.environ.get("PAPERLENS_DATA_DIR", ".paperlens")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

logger = setup_logging(DATA_DIR)

# V4.6-3：arXiv 代理缺失时启动告警——曾因 .env 丢失 PAPERLENS_ARXIV_PROXY
# 导致全部 arXiv 调用直连、下载间歇挂起（用户误以为导入卡死）
if not os.environ.get("PAPERLENS_ARXIV_PROXY"):
    logger.warning(
        "PAPERLENS_ARXIV_PROXY 未设置——arXiv 调用将直连，HTML/图片/PDF 下载可能挂起"
    )

repository = Repository(os.path.join(DATA_DIR, "paperlens.db"))
executor = JobExecutor(repository, UPLOADS_DIR)

# vNext workspace-scoped storage + services (改进方案2 Phase A)
from .repositories import VNextRepository  # noqa: E402
from .services.research import ResearchService  # noqa: E402

vnext_repository = VNextRepository(os.path.join(DATA_DIR, "paperlens.db"))
research_service = ResearchService(repository, vnext_repository)

# vNext routers (workspace / projects / comparison sets / runs / termbase / memory)
from .routers import vnext_router  # noqa: E402

app.include_router(vnext_router)

MAX_UPLOAD_MB = int(os.environ.get("PAPERLENS_MAX_PDF_MB", "80"))
# 每用户默认论文配额（V3.6）：guest 与任何 X-User-Id 用户共用同一上限
USER_PAPER_QUOTA = int(os.environ.get("PAPERLENS_USER_QUOTA", "300"))


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------
@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    job = repository.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return {
        "job_id": job.job_id,
        "job_type": job.job_type.value,
        "paper_id": job.paper_id,
        "paper_version_id": job.paper_version_id,
        "status": job.status.value,
        "progress": job.progress(),
        "stages": {key: stage.model_dump(mode="json") for key, stage in job.stages.items()},
        "error_code": job.error_code,
        "error_message": job.error_message,
        "result_uri": job.result_uri,
        "created_at": job.created_at,
    }


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    return StreamingResponse(
        bus.stream(job_id), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


# --------------------------------------------------------------------------
# Papers: upload / arXiv import
# --------------------------------------------------------------------------
def _title_candidates_from_filename(file_name: str) -> list[str]:
    """Candidate arXiv search titles from a PDF file name.

    First tries the file name as an arXiv id ("1706.03762",
    "arXiv_1607.06450v2"); otherwise hyphen/underscore/dot separators
    become spaces, noise words ("final", "v2", "draft"...) are stripped and
    the remainder is a title-search candidate.
    """
    import re as _re

    base = Path(file_name).stem.strip()
    candidates: list[str] = []
    for pattern in (
        r"(?i)(?:^|_|-|\s)arxiv[_-]?(\d{4}\.\d{4,5}(?:v\d+)?)$",
        r"(?i)(?:^|_|-|\s)(\d{4}\.\d{4,5}(?:v\d+)?)(?:$|_|-|\s)",
    ):
        match = _re.search(pattern, base)
        if match:
            candidates.append(match.group(1))
            break
    if candidates:
        return candidates  # a real arXiv id beats any title guess
    cleaned = _re.sub(r"[_\-.]", " ", base)
    cleaned = _re.sub(
        r"(?i)\b(final|draft|revision|manuscript|paper|camera\s*ready|submitted|accepted|v\d+)\b",
        " ",
        cleaned,
    )
    cleaned = _re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) >= 8:
        candidates.append(cleaned)
    return candidates


def _pdf_first_page_title(pdf_path: str) -> str:
    """Largest-font text span on page 1 as a title candidate (best effort).

    arXiv first pages carry a large-font header line ("arXiv:1506.02640v5
    [cs.CV] 9 May 2016") that must not shadow the actual title.
    """
    try:
        import fitz  # PyMuPDF

        document = fitz.open(pdf_path)
        page = document[0]
        spans: list[tuple[float, str]] = []
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if len(text) > 12 and not re.match(
                        r"(?i)arXiv\s*:\s*\d{4}\.\d{4,5}", text
                    ):
                        spans.append((float(span.get("size", 0.0)), text))
        document.close()
        if not spans:
            return ""
        spans.sort(key=lambda item: item[0], reverse=True)
        best_size = spans[0][0]
        # titles often span several lines at the same size; join them in
        # reading order until the font size drops
        title_lines = [
            (line_index, text)
            for line_index, (size, text) in enumerate(spans)
            if size >= best_size - 1.5
        ]
        title_lines.sort(key=lambda item: item[0])
        title = " ".join(text for _, text in title_lines)
        return title if len(title) <= 200 else title[:200]
    except Exception:  # noqa: BLE001 - title extraction is best-effort
        pass
    # PyMuPDF may be absent on the server; fall back to pdfplumber (always a dep)
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as document:
            page = document.pages[0]
            lines: list[tuple[float, str]] = []
            for line in page.extract_text_lines():
                text = line["text"].strip()
                if len(text) > 12 and not re.match(
                    r"(?i)arXiv\s*:\s*\d{4}\.\d{4,5}", text
                ):
                    lines.append((float(line.get("size", 0.0)), text))
        if not lines:
            return ""
        lines.sort(key=lambda item: item[0], reverse=True)
        best_size = lines[0][0]
        title_lines = [
            text for size, text in lines if size >= best_size - 1.5
        ]
        title = " ".join(title_lines)
        return title if len(title) <= 200 else title[:200]
    except Exception:  # noqa: BLE001 - best-effort by design
        return ""


def _request_user_id(request) -> str:
    """User identity from the X-User-Id header; falls back to guest."""
    return (request.headers.get("X-User-Id") or "guest").strip()[:64] or "guest"


def _enforce_paper_quota(user_id: str) -> None:
    """每用户论文配额（默认 300 篇，V3.6）：超出拒绝新导入。"""
    count = repository.count_papers_by_user(user_id)
    if count >= USER_PAPER_QUOTA:
        raise HTTPException(
            403,
            f"论文数量已达上限（{USER_PAPER_QUOTA} 篇/用户），请先删除部分论文。",
        )


def _arxiv_html_with_pdf_fallback(
    arxiv_id: str, pdf_path: str, file_name: str, job: object, user_id: str = "guest"
) -> object:
    """Source-first with degradation: arXiv HTML when available, else the
    uploaded PDF through the same job ."""
    try:
        return create_arxiv_html_job(
            executor,
            repository,
            arxiv_id=arxiv_id,
            job=job,
            user_id=user_id,
            pdf_path=pdf_path,
        )
    except Exception as exc:  # noqa: BLE001 - HTML coverage is not 100%
        logger.warning(
            "job %s: arXiv HTML %s unavailable (%s: %s) -> PDF fallback",
            getattr(job, "job_id", "?"),
            arxiv_id,
            type(exc).__name__,
            exc,
        )
        return create_parse_job(
            executor, repository, pdf_path=pdf_path, file_name=file_name, job=job, user_id=user_id
        )


def _match_arxiv_by_title(client, title: str) -> str | None:
    """Search arXiv by title; return the best-matching arXiv id or None.

    The extracted title may be truncated ("You Only Look Once:" vs the full
    "You Only Look Once: Unified, ..."), so the score also checks how well
    the query matches the candidate's prefix.
    """
    from difflib import SequenceMatcher

    candidates = client.search_arxiv_by_title(title)
    if not candidates:
        return None
    best: tuple[float, str] = (0.0, "")
    query = title.casefold()
    for candidate in candidates:
        candidate_title = candidate.title.casefold()
        score = max(
            SequenceMatcher(None, query, candidate_title).ratio(),
            SequenceMatcher(None, query, candidate_title[: len(query)]).ratio(),
        )
        if score > best[0]:
            best = (score, candidate.arxiv_id or "")
    return best[1] if best[0] >= 0.70 and best[1] else None


@app.post("/api/papers/upload")
async def upload_paper(file: UploadFile = File(...), raw_request: Request = None) -> dict[str, object]:  # noqa: B008
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")
    if not raw.startswith(b"%PDF-"):
        raise HTTPException(400, "not a PDF file")
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"PDF 超过 {MAX_UPLOAD_MB}MB 限制")
    user_id = _request_user_id(raw_request)
    _enforce_paper_quota(user_id)
    name = Path(file.filename or "paper.pdf").name
    safe_name = "".join(char for char in name if char.isalnum() or char in "._- ")
    target = os.path.join(UPLOADS_DIR, f"{uuid.uuid4().hex[:8]}-{safe_name}")
    with open(target, "wb") as handle:
        handle.write(raw)

    # Source-first: if the PDF has an arXiv version with
    # HTML, parse the HTML instead of the fragmented PDF. Search by file name
    # first, then by the page-1 title; every step degrades to the PDF pipeline.
    matched_arxiv: str | None = None
    try:
        from paperlens_core.scholarly import ScholarlyClient

        candidates = _title_candidates_from_filename(safe_name)
        if candidates and re.match(r"^\d{4}\.\d{4,5}(?:v\d+)?$", candidates[0]):
            matched_arxiv = candidates[0]  # file name IS an arXiv id
        else:
            with ScholarlyClient(contact_email="paperlens@example.com") as client:
                for title in candidates:
                    matched_arxiv = _match_arxiv_by_title(client, title)
                    if matched_arxiv:
                        break
                if not matched_arxiv:
                    page_title = _pdf_first_page_title(target)
                    if page_title:
                        matched_arxiv = _match_arxiv_by_title(client, page_title)
    except Exception as exc:  # noqa: BLE001 - arXiv lookup is an enhancement
        logger.warning("upload %s: arXiv lookup failed (%s)", safe_name, exc)
        matched_arxiv = None

    if matched_arxiv:
        job = new_job(JobType.PARSE)
        executor.submit(
            job,
            # HTML 覆盖并非 100%：匹配到 arXiv 但
            # LaTeXML HTML 不可用（老论文常见）时，同一 job 回退 PDF 管线
            lambda current: _arxiv_html_with_pdf_fallback(
                matched_arxiv, target, safe_name, current, user_id
            ),
        )
        logger.info("upload %s -> matched arXiv %s (job %s)", safe_name, matched_arxiv, job.job_id)
        return {
            "job_id": job.job_id,
            "status": "QUEUED",
            "matched_arxiv": matched_arxiv,
        }

    logger.info("upload %s -> PDF pipeline (no arXiv match)", safe_name)
    job = new_job(JobType.PARSE)
    executor.submit(
        job,
        lambda current: create_parse_job(
            executor, repository, pdf_path=target, file_name=safe_name, job=current, user_id=user_id
        ),
    )
    return {"job_id": job.job_id, "status": "QUEUED", "matched_arxiv": ""}


@app.post("/api/papers/import/arxiv")
def import_arxiv(request: ArxivImportRequest, raw_request: Request = None) -> dict[str, object]:
    user_id = _request_user_id(raw_request)
    _enforce_paper_quota(user_id)
    try:
        arxiv_id = normalize_arxiv_input(request.arxiv_input)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    contact = os.environ.get("CONTACT_EMAIL", "")

    def run(job) -> None:
        # Source-first: arXiv HTML when available (semantic structure intact),
        # otherwise fall back to the PDF pipeline.
        try:
            create_arxiv_html_job(executor, repository, arxiv_id=arxiv_id, job=job, user_id=user_id)
        except Exception as exc:  # noqa: BLE001 - fall back to PDF
            logger.warning("arxiv import %s HTML failed (%s) -> PDF fallback", arxiv_id, exc)
            pdf_path = download_pdf(arxiv_id, UPLOADS_DIR, contact_email=contact)
            create_parse_job(
                executor,
                repository,
                pdf_path=pdf_path,
                file_name=f"arxiv-{arxiv_id}.pdf",
                job=job,
                user_id=user_id,
            )

    job = new_job(JobType.PARSE)
    executor.submit(job, run)
    return {"job_id": job.job_id, "status": "QUEUED", "arxiv_id": arxiv_id}


@app.delete("/api/papers/{paper_id}")
def delete_paper(paper_id: str) -> dict[str, str]:
    if repository.get_paper(paper_id) is None:
        raise HTTPException(404, "paper not found")
    repository.delete_paper(paper_id)
    return {"status": "deleted"}


@app.get("/api/papers")
def list_papers() -> list[dict[str, object]]:
    return repository.list_papers()


@app.get("/api/papers/{paper_id}")
def get_paper(paper_id: str) -> dict[str, object]:
    paper = repository.get_paper(paper_id)
    if paper is None:
        raise HTTPException(404, "paper not found")
    return paper.model_dump(mode="json")


# --------------------------------------------------------------------------
# Document reading
# --------------------------------------------------------------------------
def _require_version(version_id: str):
    version = repository.get_version(version_id)
    if version is None:
        raise HTTPException(404, "version not found")
    return version


@app.get("/api/papers/{paper_id}/versions")
def list_versions(paper_id: str) -> list[dict[str, object]]:
    if repository.get_paper(paper_id) is None:
        raise HTTPException(404, "paper not found")
    return _load_versions(paper_id)


def _load_versions(paper_id: str) -> list[dict[str, object]]:
    # versions are stored with the paper; simplest: scan rows
    rows = repository._conn.execute(
        "SELECT * FROM paper_versions WHERE paper_id=?", (paper_id,)
    ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/papers/{paper_id}/outline")
def get_outline(paper_id: str, version_id: str = Query(default="")) -> dict[str, object]:
    version = _pick_version(paper_id, version_id)
    sections = [Section.model_validate(item) for item in repository.load_document(version.version_id, "sections")]
    return {"paper_id": paper_id, "version_id": version.version_id, "sections": [s.model_dump(mode="json") for s in sections]}


@app.get("/api/papers/{paper_id}/document")
def get_document(paper_id: str, version_id: str = Query(default=""), page: int | None = None) -> dict[str, object]:
    version = _pick_version(paper_id, version_id)
    blocks = [Block.model_validate(item) for item in repository.load_document(version.version_id, "blocks")]
    if page is not None:
        blocks = [block for block in blocks if block.page == page]
    blocks.sort(key=lambda block: (block.page, block.paragraph_index))
    return {
        "paper_id": paper_id,
        "version_id": version.version_id,
        "page_count": version.page_count,
        "blocks": [block.model_dump(mode="json") for block in blocks],
    }


@app.get("/api/papers/{paper_id}/pdf")
def get_pdf(paper_id: str, version_id: str = Query(default="")) -> FileResponse:
    version = _pick_version(paper_id, version_id)
    # V4.6-5（检查 1）：懒下载——导入不再同步下载原版 PDF（曾占
    # layout_and_text 25-56s），首次打开原版模式时经代理获取并缓存
    if not Path(version.file_path).exists():
        from paperlens_core.documents import PaperSource

        if version.source == PaperSource.ARXIV:
            try:
                meta = repository.load_document(version.version_id, "paper_meta")
                arxiv_id = ""
                if meta:
                    arxiv_id = str(meta[0].get("arxiv_id") or "")
                if not arxiv_id and version.file_name.startswith("arxiv-"):
                    arxiv_id = version.file_name[len("arxiv-"):]
                if arxiv_id:
                    downloaded = download_pdf(
                        arxiv_id, UPLOADS_DIR, contact_email="paperlens@example.com"
                    )
                    repository.update_version_file_path(version.version_id, downloaded)
                    version.file_path = downloaded
            except Exception as exc:  # noqa: BLE001 - lazy download is best-effort
                logger.warning("lazy pdf download failed for %s: %s", paper_id, exc)
    if not Path(version.file_path).exists():
        raise HTTPException(404, "pdf file missing")
    # 2026-08-06：原版 PDF 允许浏览器缓存（1 小时）——nginx 对 /api/ 统一
    # no-store 会让 pdf.js 每次重下 15MB，1Mbps 带宽下点"原版"要等 2 分钟；
    # 可缓存后浏览器命中（配合前端进入论文页即预取），点击原版秒开
    return FileResponse(
        version.file_path,
        media_type="application/pdf",
        headers={"Cache-Control": "public, max-age=3600"},
    )


def _pick_version(paper_id: str, version_id: str):
    versions = _load_versions(paper_id)
    if not versions:
        raise HTTPException(404, "paper has no versions")
    chosen = next((v for v in versions if v["version_id"] == version_id), versions[0])
    return _require_version(chosen["version_id"])


# --------------------------------------------------------------------------
# Assets
# --------------------------------------------------------------------------
@app.get("/api/papers/{paper_id}/assets")
def list_assets(paper_id: str, version_id: str = Query(default="")) -> list[dict[str, object]]:
    version = _pick_version(paper_id, version_id)
    assets = [Asset.model_validate(item) for item in repository.load_document(version.version_id, "assets")]
    return [asset.model_dump(mode="json") for asset in assets]


@app.get("/api/assets/{asset_id}")
def get_asset(asset_id: str) -> dict[str, object]:
    for paper in repository.list_papers():
        for version_row in _load_versions(str(paper["paper_id"])):
            for item in repository.load_document(version_row["version_id"], "assets"):
                asset = Asset.model_validate(item)
                if asset.asset_id == asset_id:
                    return asset.model_dump(mode="json")
    raise HTTPException(404, "asset not found")


def _pdf_highres_figure(version_row: object, asset: Asset) -> bytes | None:
    """HTML 论文图的高清来源（V3.13）：arXiv HTML 位图仅 ~700-1000px，
    PDF 里嵌入的源图通常更高清。按文档顺序匹配嵌入图（过滤小图），
    PyMuPDF 3x 渲染 + bbox 裁剪。顺序/区域不匹配时返回 None，调用方回退
    原图。"""
    import re as _re

    import fitz

    if not asset.content_uri or not version_row.get("file_path"):
        return None
    match = _re.search(r"fig-html-(\d+)", asset.asset_id)
    if not match:
        return None
    target = int(match.group(1))
    try:
        document = fitz.open(version_row["file_path"])
        infos: list[tuple[int, tuple[float, float, float, float]]] = []
        for page_number in range(document.page_count):
            page = document[page_number]
            for info in page.get_image_info():
                bbox = info.get("bbox")
                if bbox and (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) > 10000:
                    infos.append((page_number, tuple(bbox)))
        document.close()
    except Exception:  # noqa: BLE001 - best-effort by design
        return None
    if len(infos) < target:
        return None
    page_number, bbox = infos[target - 1]
    try:
        document = fitz.open(version_row["file_path"])
        page = document[page_number]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=fitz.Rect(bbox))
        data = pixmap.tobytes("png")
        document.close()
        return data
    except Exception:  # noqa: BLE001 - best-effort by design
        return None


@app.get("/api/assets/{asset_id}/download")
def download_asset_content(asset_id: str) -> Response:
    """HTML 论文图下载（V3.9b）：导入时已预下载到服务器本地（local_file），
    直接返回本地文件，不再回源 arXiv；旧数据无本地文件时回源拉取并落盘
    缓存，此后也走本地。PDF 论文无 content_uri 时 404，前端回退裁剪。"""
    from pathlib import Path as _Path

    from paperlens_core.net import make_arxiv_httpx_client

    for paper in repository.list_papers():
        for version_row in _load_versions(str(paper["paper_id"])):
            for item in repository.load_document(version_row["version_id"], "assets"):
                asset = Asset.model_validate(item)
                if asset.asset_id != asset_id or not (asset.content_uri or asset.local_file):
                    continue
                # 高清优先（V3.13）：HTML 论文图对比 PDF 嵌入源图（3x 裁剪）与
                # arXiv 位图，取像素更多的一方——低 DPI 嵌入的 PDF 不劣于原图。
                # HTML 论文图 bbox 恒为 (0,0,0,0)（无物理版面），跳过裁剪
                # 对比（V3.23），直接走本地/回源
                import fitz as _fitz

                has_physical_bbox = (
                    asset.bbox[2] - asset.bbox[0] > 1 and asset.bbox[3] - asset.bbox[1] > 1
                )
                highres = _pdf_highres_figure(version_row, asset) if has_physical_bbox else None
                original: bytes | None = None
                if asset.local_file and _Path(asset.local_file).exists():
                    with open(asset.local_file, "rb") as handle:
                        original = handle.read()
                if highres and original:
                    high_pixels = _fitz.Pixmap(highres).width * _fitz.Pixmap(highres).height
                    original_pixels = _fitz.Pixmap(original).width * _fitz.Pixmap(original).height
                    payload = highres if high_pixels >= original_pixels else original
                    return Response(
                        content=payload,
                        media_type="image/png",
                        headers={"Content-Disposition": f'attachment; filename="{asset_id}.png"'},
                    )
                if highres:
                    return Response(
                        content=highres,
                        media_type="image/png",
                        headers={"Content-Disposition": f'attachment; filename="{asset_id}.png"'},
                    )
                if original:
                    return Response(
                        content=original,
                        media_type="image/png",
                        headers={"Content-Disposition": f'attachment; filename="{asset_id}.png"'},
                    )
                # 回源拉取并落盘缓存（旧论文的首次下载）
                try:
                    asset_dir = os.path.join(UPLOADS_DIR, "assets", version_row["version_id"])
                    os.makedirs(asset_dir, exist_ok=True)
                    local_path = os.path.join(asset_dir, f"{asset_id}.png")
                    if not _Path(local_path).exists():
                        with make_arxiv_httpx_client(timeout=40) as client:
                            response = client.get(asset.content_uri)
                            response.raise_for_status()
                        with open(local_path, "wb") as handle:
                            handle.write(response.content)
                    asset = asset.model_copy(update={"local_file": local_path})
                    updated = [
                        asset.model_dump(mode="json")
                        if item.get("asset_id") == asset_id
                        else item
                        for item in repository.load_document(
                            version_row["version_id"], "assets"
                        )
                    ]
                    repository.store_document(version_row["version_id"], "assets", updated)
                    return FileResponse(
                        local_path,
                        media_type="image/png",
                        headers={"Content-Disposition": f'attachment; filename="{asset_id}.png"'},
                    )
                except Exception as exc:  # noqa: BLE001 - surface fetch failure
                    logger.warning("asset %s download failed: %s", asset_id, exc)
                    raise HTTPException(502, "图片拉取失败") from exc
    raise HTTPException(404, "asset not found or has no content_uri")


# --------------------------------------------------------------------------
# Sessions / chat (evidence QA with SSE)
# --------------------------------------------------------------------------
@app.post("/api/sessions")
def create_session(paper_id: str, version_id: str = Query(default=""), user_id: str = "guest") -> dict[str, str]:
    version = _pick_version(paper_id, version_id)
    session_id = f"ses-{uuid.uuid4().hex[:12]}"
    repository.create_session(session_id, user_id, version.version_id)
    return {"session_id": session_id, "paper_version_id": version.version_id}


def _reader_event_stream(
    session_id: str, request: ChatRequest
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Shared reader execution for the buffered and the streaming chat paths."""
    sessions = repository._conn.execute(
        "SELECT * FROM sessions WHERE session_id=?", (session_id,)
    ).fetchone()
    if sessions is None:
        raise HTTPException(404, "session not found")
    version = _require_version(sessions["paper_version_id"])
    # V4.1：DocumentGraph 统一——documents.Chunk 直接进 reader，
    # 不再经 _legacy_chunks 桥接（已删除）
    chunks = [Chunk.model_validate(item) for item in repository.load_document(version.version_id, "chunks")]

    from paperlens_core.config import Settings
    from paperlens_core.llm import OpenAICompatibleModel
    from paperlens_core.reader import PaperReader

    settings = Settings()
    reader = PaperReader(OpenAICompatibleModel(settings))

    events, agent_context = _prepare_paper_agent(
        question=request.question,
        chunks=chunks,
        workspace_id=str(sessions["user_id"] or "guest"),
        paper_version_id=version.version_id,
    )
    answer: dict[str, object] = {}
    for event in reader.run_events(
        question=request.question,
        chunks=chunks,
        thread_id=session_id,
        top_k=settings.paperlens_top_k,
        cache_namespace=version.version_id,
        context_scope=request.context,
        context_block_ids=request.context_block_ids,
        history=[
            {"role": m["role"], "content": str(m["content"])}
            for m in repository.list_messages(session_id)[-6:]
        ] + ([{"role": "assistant", "content": agent_context}] if agent_context else []),
        task_id=request.task_id,
    ):
        if event.event in {"stage_started", "retrieval_hits", "claim_validated", "claim_rejected"}:
            events.append({"event": event.event, "payload": event.payload})
        elif event.event == "completed":
            answer = event.payload.get("answer", {})
        elif event.event == "error":
            raise HTTPException(502, f"{event.payload.get('code')}: {event.payload.get('message')}")
    return events, answer


@app.post("/api/sessions/{session_id}/messages")
async def chat_message(session_id: str, request: ChatRequest) -> dict[str, object]:
    events, answer = _reader_event_stream(session_id, request)
    repository.append_message(session_id, "user", request.question, [])
    message_id = repository.append_message(
        session_id,
        "assistant",
        str(answer.get("answer", "当前证据不足，无法给出可靠回答。")),
        [item for item in events if item["event"] == "claim_validated"],
    )
    return {"message_id": message_id, "answer": answer, "events": events}


def _sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _prepare_paper_agent(
    *,
    question: str,
    chunks: list[Chunk],
    workspace_id: str,
    paper_version_id: str,
) -> tuple[list[dict[str, object]], str]:
    """Run adaptive paper capabilities before evidence-grounded answering.

    QUICK questions stay on PaperReader's fast path. Analytic/deep questions
    execute the bounded capability plan; its findings are supplied as planning
    context, while PaperReader remains responsible for claim-level evidence.
    """
    from paperlens_core.agents import DepthRouter
    from paperlens_core.agents.executor import execute_run
    from paperlens_core.agents.planner import create_adaptive_run_plan
    from paperlens_core.agents.tools import build_default_registry
    from paperlens_core.retrieval.lexical import TextUnit

    routed = DepthRouter().route(question)
    if routed.depth.value == "QUICK":
        return [], ""
    run = create_adaptive_run_plan(
        run_id=f"paper-agent-{uuid.uuid4().hex[:10]}",
        workspace_id=workspace_id,
        project_id="",
        question=question,
        scope_paper_ids=[paper_version_id],
        depth=routed.depth,
    )
    corpus = [
        TextUnit(
            unit_id=chunk.chunk_id,
            paper_version_id=paper_version_id,
            text=chunk.text,
            section_path=chunk.section_path,
            page=chunk.page_start,
        )
        for chunk in chunks
    ]
    execute_run(run, registry=build_default_registry(corpus=corpus))
    events = [
        {
            "event": "stage_started",
            "payload": {
                "stage": task.tool,
                "label": task.name,
                "depth": routed.depth.value,
            },
        }
        for task in run.tasks
        if task.tool
    ]
    context_lines = [
        f"Paper Agent 预分析深度：{routed.depth.value}。以下内容仅作检索规划，最终答案必须重新绑定原文证据："
    ]
    context_lines.extend(
        f"- [{finding.kind.value}] {finding.statement}"
        for finding in run.structured_findings[:6]
    )
    return events, "\n".join(context_lines)


@app.post("/api/sessions/{session_id}/messages/stream")
async def chat_message_stream(session_id: str, request: ChatRequest) -> StreamingResponse:
    """SSE variant : claims appear as they are verified,
    not after the whole run. The buffered endpoint stays for compatibility."""

    def event_source():
        # re-run inside the request context so the model client is fresh
        sessions = repository._conn.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if sessions is None:
            yield _sse("error", {"code": "UNKNOWN_SESSION", "message": "会话不存在"})
            return
        # V4.0-2：流开始时即持久化 user 消息（中途 error 也不丢历史）
        # V4.6-0：history 必须先于追加读取——否则包含刚写入的当前问题
        history = [
            {"role": m["role"], "content": str(m["content"])}
            for m in repository.list_messages(session_id)[-6:]
        ]
        repository.append_message(session_id, "user", request.question, [])
        version = _require_version(sessions["paper_version_id"])
        # V4.1：documents.Chunk 直接进 reader，不再经 _legacy_chunks 桥接
        chunks = [Chunk.model_validate(item) for item in repository.load_document(version.version_id, "chunks")]

        from paperlens_core.config import Settings
        from paperlens_core.llm import OpenAICompatibleModel
        from paperlens_core.reader import PaperReader

        settings = Settings()
        reader = PaperReader(OpenAICompatibleModel(settings))
        agent_events, agent_context = _prepare_paper_agent(
            question=request.question,
            chunks=chunks,
            workspace_id=str(sessions["user_id"] or "guest"),
            paper_version_id=version.version_id,
        )
        for agent_event in agent_events:
            yield _sse(agent_event["event"], agent_event["payload"])
        claim_events: list[dict[str, object]] = []
        final_answer: dict[str, object] = {}
        for event in reader.run_events(
            question=request.question,
            chunks=chunks,
            thread_id=session_id,
            top_k=settings.paperlens_top_k,
            cache_namespace=version.version_id,
            context_scope=request.context,
            context_block_ids=request.context_block_ids,
            history=history + ([{"role": "assistant", "content": agent_context}] if agent_context else []),
            task_id=request.task_id,
        ):
            if event.event in {"stage_started", "retrieval_hits", "claim_rejected"}:
                yield _sse(event.event, event.payload)
            elif event.event == "claim_validated":
                claim_events.append({"event": event.event, "payload": event.payload})
                yield _sse("claim_validated", event.payload)
            elif event.event == "completed":
                final_answer = event.payload.get("answer", {})
                final_timings = event.payload.get("stage_timings")
            elif event.event == "error":
                yield _sse(
                    "error",
                    {
                        "code": event.payload.get("code"),
                        "message": event.payload.get("message"),
                    },
                )
                return
        message_id = repository.append_message(
            session_id,
            "assistant",
            str(final_answer.get("answer", "当前证据不足，无法给出可靠回答。")),
            claim_events,
        )
        yield _sse(
            "completed",
            {
                "message_id": message_id,
                "answer": final_answer,
                "stage_timings": final_timings or {},
            },
        )

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/sessions/{session_id}/messages")
def list_messages(session_id: str) -> list[dict[str, object]]:
    return repository.list_messages(session_id)


@app.get("/api/sessions")
def list_sessions(paper_id: str, version_id: str = Query(default=""), user_id: str = "guest") -> list[dict[str, object]]:
    """V4.6-1：论文的会话列表（标题/时间），前端恢复/切换用。"""
    version = _pick_version(paper_id, version_id)
    return repository.list_sessions(version.version_id, user_id)


@app.post("/api/sessions/{session_id}/rename")
def rename_session(session_id: str, request: RenameRequest) -> dict[str, str]:
    repository.rename_session(session_id, request.title.strip()[:80])
    return {"status": "ok"}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, str]:
    repository.delete_session(session_id)
    return {"status": "deleted"}


@app.get("/api/sessions/latest")
def latest_session(paper_id: str, version_id: str = Query(default=""), user_id: str = "guest") -> dict[str, str]:
    """V4.0-3：进入论文时恢复最近会话。

    按 (paper 的当前版本, 用户) 找最近一条会话；无则 404 由前端新建。
    """
    version = _pick_version(paper_id, version_id)
    row = repository._conn.execute(
        "SELECT session_id FROM sessions WHERE paper_version_id=? AND user_id=? "
        "ORDER BY created_at DESC LIMIT 1",
        (version.version_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "no session yet")
    return {"session_id": row["session_id"], "paper_version_id": version.version_id}


# --------------------------------------------------------------------------
# References
# --------------------------------------------------------------------------
@app.post("/api/references/{reference_id}/resolve")
def resolve_reference(reference_id: str, request: ResolveRequest | None = None) -> dict[str, object]:
    """Online identity verification (Crossref/arXiv) for one reference.

    Implements the waterfall in  (DOI/arXiv exact first,
    then Crossref multi-field scoring with AMBIGUOUS detection). The resolved
    record is persisted so the status survives refresh; the client refetches
    the reference list afterwards.
    """
    from paperlens_core.references import ReferenceRecord
    from paperlens_core.scholarly import ScholarlyClient

    for paper in repository.list_papers():
        for version_row in _load_versions(str(paper["paper_id"])):
            for record in list_references(str(paper["paper_id"]), version_row["version_id"]):
                if record["reference_id"] != reference_id:
                    continue
                record_model = ReferenceRecord.model_validate(record)
                contact_email = (request.contact_email or "student@example.invalid") if request else "student@example.invalid"
                with ScholarlyClient(contact_email=contact_email) as client:
                    resolved = client.resolve_reference(record_model)
                # persist the resolved record next to the stored references
                persisted = repository.load_document(version_row["version_id"], "references")
                if persisted:
                    updated = []
                    for item in persisted:
                        if item.get("reference_id") == reference_id:
                            item.update(resolved.model_dump(mode="json"))
                        updated.append(item)
                    repository.store_document(version_row["version_id"], "references", updated)
                return {
                    "reference_id": reference_id,
                    "identity_status": resolved.identity_status.value,
                    "identifier_resolution": resolved.identifier_resolution,
                    "record_match": resolved.record_match,
                    "doi": resolved.doi,
                    "arxiv_id": resolved.arxiv_id,
                    "provider_evidence": resolved.provider_evidence,
                    "errors": client.last_errors,
                }
    raise HTTPException(404, "reference not found")


# 批量核验进度（V4.8）：进程内 dict，单 worker uvicorn 跨请求共享
_resolve_all_progress: dict[str, dict[str, object]] = {}


@app.post("/api/papers/{paper_id}/references/resolve-all")
def resolve_all_references(
    paper_id: str, version_id: str = Query(default="")
) -> dict[str, object]:
    """Batch identity verification for all references of a paper (V4.8).

    与单条端点走同一 Crossref/arXiv 瀑布式匹配（§11.4）。大论文（200+ 条
    全模糊搜索）可跑数分钟——后台线程执行 + 进度状态由
    resolve-all/status 轮询（前端 2s），完成后一次性持久化。
    """
    version = _pick_version(paper_id, version_id)
    persisted = repository.load_document(version.version_id, "references")
    if not persisted:
        return {"total": 0, "message": "该论文还没有可核验的参考文献"}
    state = _resolve_all_progress.get(version.version_id)
    if state and state.get("state") == "running":
        return {"total": len(persisted), "state": "running"}
    from paperlens_core.models import ReferenceRecord
    from paperlens_core.scholarly import ScholarlyClient

    state = {
        "state": "running",
        "done": 0,
        "total": len(persisted),
        "verified": 0,
        "probable": 0,
        "ambiguous": 0,
        "unresolved": 0,
    }
    _resolve_all_progress[version.version_id] = state

    def run() -> None:
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            records = [ReferenceRecord.model_validate(item) for item in persisted]

            def worker(record: ReferenceRecord) -> ReferenceRecord:
                # 每 worker 独立 client（httpx.Client 线程安全但 last_errors
                # 是实例状态，共享会跨请求污染）
                with ScholarlyClient(contact_email="student@example.invalid") as client:
                    return client.resolve_reference(record)

            updated: list[dict[str, object]] = []
            # 244 条无 ID 条目全模糊搜索时串行约 18 分钟——4 并发折半以上
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(worker, record) for record in records]
                for future in as_completed(futures):
                    resolved = future.result()
                    updated.append(resolved.model_dump(mode="json"))
                    state["done"] = int(state["done"]) + 1
                    status_key = resolved.identity_status.value.lower()
                    state[status_key] = int(state[status_key]) + 1
                    # 边核验边持久化（改进 2026-08-05）：每 10 条落一次库，
                    # 前端轮询进度时同时刷新列表即可看到逐条结果
                    if int(state["done"]) % 10 == 0:
                        repository.store_document(version.version_id, "references", updated)
            repository.store_document(version.version_id, "references", updated)
            state["state"] = "done"
        except Exception as exc:  # noqa: BLE001
            state["state"] = "error"
            state["error"] = str(exc)

    import threading

    threading.Thread(target=run, daemon=True).start()
    return {"total": len(persisted), "state": "running"}


@app.get("/api/papers/{paper_id}/references/resolve-all/status")
def resolve_all_status(
    paper_id: str, version_id: str = Query(default="")
) -> dict[str, object]:
    """批量核验进度（前端 2s 轮询）。"""
    version = _pick_version(paper_id, version_id)
    return _resolve_all_progress.get(
        version.version_id,
        {"state": "idle", "done": 0, "total": 0},
    )


@app.post("/api/references/{reference_id}/import")
def import_reference(reference_id: str) -> dict[str, object]:
    """One-click import of a referenced paper .

    Resolves arXiv id / DOI to a public PDF where possible and enqueues a
    PARSE job; never bypasses paywalls or scrapes unofficial sources.
    """
    for paper in repository.list_papers():
        for version_row in _load_versions(str(paper["paper_id"])):
            records = list_references(str(paper["paper_id"]), version_row["version_id"])
            for record in records:
                if record["reference_id"] != reference_id:
                    continue
                if record.get("arxiv_id"):
                    try:
                        pdf_path = download_pdf(
                            record["arxiv_id"], UPLOADS_DIR, contact_email=os.environ.get("CONTACT_EMAIL", "")
                        )
                        job = new_job(JobType.PARSE)
                        executor.submit(
                            job,
                            lambda current, pdf_path=pdf_path, arxiv_id=record["arxiv_id"]: create_parse_job(
                                executor,
                                repository,
                                pdf_path=pdf_path,
                                file_name=f"arxiv-{arxiv_id}.pdf",
                                job=current,
                            ),
                        )
                        return {"job_id": job.job_id, "status": "QUEUED", "source": "arxiv"}
                    except Exception as exc:  # noqa: BLE001
                        return {"status": "FAILED", "error": str(exc)}
                return {
                    "status": "NO_PUBLIC_FULLTEXT",
                    "message": "已找到论文元数据，但没有找到可公开下载的全文。请上传你合法获取的 PDF。",
                }
    raise HTTPException(404, "reference not found")


@app.get("/api/papers/{paper_id}/callouts")
def list_callouts(paper_id: str, version_id: str = Query(default="")) -> list[dict[str, object]]:
    version = _pick_version(paper_id, version_id)
    return repository.load_document(version.version_id, "callouts")


@app.get("/api/papers/{paper_id}/page-quality")
def list_page_quality(paper_id: str, version_id: str = Query(default="")) -> list[dict[str, object]]:
    """Per-page parse quality verdicts ."""
    version = _pick_version(paper_id, version_id)
    return repository.load_document(version.version_id, "page_quality")


@app.get("/api/papers/{paper_id}/meta")
def get_paper_meta(paper_id: str, version_id: str = Query(default="")) -> dict[str, object]:
    """Title/authors/abstract for the arXiv-style header (V3.6)."""
    version = _pick_version(paper_id, version_id)
    stored = repository.load_document(version.version_id, "paper_meta")
    meta = dict(stored[0]) if stored and isinstance(stored[0], dict) else {}
    if not meta.get("abstract"):
        from paperlens_core.documents import Block as BlockIR

        blocks = [
            BlockIR.model_validate(item)
            for item in repository.load_document(version.version_id, "blocks")
        ]
        from paperlens_core.metadata import meta_with_abstract

        meta = meta_with_abstract(meta, blocks)
    return meta


@app.get("/api/papers/{paper_id}/sample-questions")
def get_sample_questions(
    paper_id: str, version_id: str = Query(default="")
) -> dict[str, object]:
    """解析时用摘要生成的示例问题（教师优化 1，2026-08-07）——
    Agent 输入框 placeholder 动态化。未生成时返回空列表，前端回退默认文案。
    """
    version = _pick_version(paper_id, version_id)
    stored = repository.load_document(version.version_id, "sample_questions")
    questions = [str(item) for item in (stored or []) if item][:3]
    return {"questions": questions}


@app.get("/api/papers/{paper_id}/references")
def list_references(paper_id: str, version_id: str = Query(default="")) -> list[dict[str, object]]:
    version = _pick_version(paper_id, version_id)
    persisted = repository.load_document(version.version_id, "references")
    if persisted:
        return persisted
    # legacy path: parse from the References section text (PDF-imported papers)
    blocks = [Block.model_validate(item) for item in repository.load_document(version.version_id, "blocks")]
    references_sections = [s for s in [Section.model_validate(item) for item in repository.load_document(version.version_id, "sections")] if s.canonical_name == "references"]
    reference_blocks = []
    if references_sections:
        start = references_sections[0].start_page
        reference_blocks = [block for block in blocks if block.page >= start and block.block_type == BlockType.TEXT]
    # V4.2：序列化复用导入期持久化的同一形状（serialize_reference_records）
    from paperlens_core.references import parse_references, serialize_reference_records

    text = "\n".join(block.text for block in reference_blocks)
    records = parse_references(text)
    return serialize_reference_records(records, version.version_id)


# --------------------------------------------------------------------------
# V4.4 单篇旗舰功能
# --------------------------------------------------------------------------
@app.post("/api/papers/{paper_id}/analyses/method-graph")
def run_method_graph(paper_id: str, version_id: str = Query(default="")) -> dict[str, object]:
    """Method Navigator：证据绑定的方法有向图。"""
    version = _pick_version(paper_id, version_id)
    persisted = repository.load_document(version.version_id, "method_graph")
    if persisted:
        return persisted[0]
    chunks = [Chunk.model_validate(item) for item in repository.load_document(version.version_id, "chunks")]
    from paperlens_core.config import Settings
    from paperlens_core.llm import OpenAICompatibleModel
    from paperlens_core.method_graph import build_method_graph

    settings = Settings()
    graph = build_method_graph(
        model=OpenAICompatibleModel(settings),
        chunks=chunks,
        paper_id=paper_id,
        thread_id="method-graph-" + paper_id,
    )
    repository.store_document(
        version.version_id,
        "method_graph",
        [graph.model_dump(mode="json")],
    )
    return graph.model_dump(mode="json")


@app.get("/api/papers/{paper_id}/experiments")
def list_experiments(paper_id: str, version_id: str = Query(default="")) -> list[dict[str, object]]:
    """Experiment Explorer（§十·功能二）：从结构化表格确定性提取结果记录。"""
    version = _pick_version(paper_id, version_id)
    from paperlens_core.documents import Asset as AssetIR
    from paperlens_core.experiments import extract_result_records

    assets = [
        AssetIR.model_validate(item)
        for item in repository.load_document(version.version_id, "assets")
    ]
    return [
        record.model_dump(mode="json")
        for record in extract_result_records(assets)
    ]


@app.post("/api/v1/comparisons")
def create_comparison(request: ComparisonRequest) -> dict[str, object]:
    """创建并运行多篇比较（V4.7 全量修复）：

    - 后台线程执行，进度逐步持久化，前端轮询/SSE 可见（P2/3.1）
    - artifact 字段复用，缺失字段才 LLM 抽取（P3/3.2）
    - 对齐输入来自本次抽取 cells（P0/2.1），带置信度（P4/3.6）
    - 单篇失败降级不阻塞整体（P4/3.4）
    - 结果含结构化记录对比（ResultComparison，P1/2.2）
    - 统一以 version_id 为实体键（P0/3.5）
    """
    if len(set(request.paper_version_ids)) != len(request.paper_version_ids):
        raise HTTPException(400, "paper versions must be unique")
    # V4.7b：同组合最近一次 DONE 结果直接返回（避免重复 60-130s 抽取）
    # 审计 P1（2026-08-05）：缓存 key 必须包含维度，否则换维度比较会
    # 错误地复用旧结果。注意：默认字段也参与 key——旧记录无 fields 字段
    # 视为空，与"前端未传维度（默认 5 字段）"不得误命中
    DEFAULT_COMPARISON_FIELDS = [
        "task_definition",
        "method_core",
        "datasets_and_samples",
        "metrics",
        "main_results",
    ]
    wanted = sorted(request.paper_version_ids)
    effective_fields = (
        list(request.dimensions) if request.dimensions else list(DEFAULT_COMPARISON_FIELDS)
    )
    wanted_fields = sorted(effective_fields)
    for item in repository.list_comparisons(limit=10):
        if item.get("status") != "DONE":
            continue
        if sorted(item.get("paper_version_ids") or []) != wanted:
            continue
        if sorted(item.get("fields") or []) != wanted_fields:
            continue
        cached = repository.load_comparison(item["comparison_id"])
        if cached:
            cached = dict(cached)
            cached["cached"] = True
            return cached
    from paperlens_core.comparison import (
        ComparisonCell,
        PaperComparator,
        add_comparability_warnings,
        assemble_comparison,
        build_result_comparisons,
        judge_topic_alignment,
    )
    from paperlens_core.config import Settings
    from paperlens_core.llm import OpenAICompatibleModel
    from paperlens_core.models import CoverageStatus

    comparison_id = f"cmp-{uuid.uuid4().hex[:12]}"
    versions = [_require_version(vid) for vid in request.paper_version_ids]
    # 审计 P0-6（2026-08-05）：未显式传维度时默认只比较 5 个核心字段，
    # 避免 13 字段信息堆积导致"看不懂在比较什么"（effective_fields 在
    # 上方缓存 key 处已统一计算）
    fields = effective_fields
    model = OpenAICompatibleModel(Settings())
    def _cell_value(cells: list[ComparisonCell], field: str) -> str:
        return next((cell.value for cell in cells if cell.field == field), "")

    def run() -> None:
        try:
            extracted: list[ComparisonCell] = []
            evidence: dict[str, set[str]] = {}
            summaries: list[dict[str, str]] = []
            records_by_paper: dict[str, list[dict[str, object]]] = {}
            cells_by_paper: dict[str, list[ComparisonCell]] = {}
            # 审计改进（2026-08-05）：多篇 LLM 抽取并发执行——此前逐篇
            # 串行（每篇 60-130s），2-3 篇要等数分钟才出结果
            from concurrent.futures import ThreadPoolExecutor as _TPE
            from concurrent.futures import as_completed

            def extract_paper(version: object, index: int) -> dict[str, object]:
                try:
                    # P3：artifact 字段复用（task/method/datasets/metrics/...）
                    artifact = repository.load_document(
                        version.version_id, "understanding_artifact"
                    )
                    profile = (artifact[0].get("profile") if artifact else None) or {}
                    artifact_fields: dict[str, dict[str, object]] = {}
                    for cfield, afield in ARTIFACT_FIELD_MAP.items():
                        pf = (profile.get(afield) or {}) if isinstance(profile, dict) else {}
                        if pf.get("status") == "FOUND" and pf.get("value"):
                            artifact_fields[cfield] = pf
                    chunks = [
                        Chunk.model_validate(item)
                        for item in repository.load_document(version.version_id, "chunks")
                    ]
                    cells: list[ComparisonCell] = []
                    known: set[str] = set()
                    llm_fields = [f for f in fields if f not in artifact_fields]
                    if llm_fields:
                        # 每 worker 独立 model/comparator（避免共享实例状态）
                        worker_model = OpenAICompatibleModel(Settings())
                        worker_comparator = PaperComparator(worker_model)
                        llm_cells, llm_known = worker_comparator.extract_one(
                            paper_id=version.version_id,
                            chunks=chunks,
                            fields=llm_fields,
                            thread_id="compare-" + comparison_id,
                        )
                        cells.extend(llm_cells)
                        known |= llm_known
                    for cfield, pf in artifact_fields.items():
                        cells.append(
                            ComparisonCell(
                                paper_id=version.version_id,
                                field=cfield,
                                value=str(pf.get("value") or ""),
                                status=CoverageStatus.FOUND,
                                evidence_ids=[str(e) for e in (pf.get("evidence_ids") or [])][:3],
                                quotes=[],
                                locators=[
                                    dict(item) for item in (pf.get("evidence_locators") or [])
                                ][:3],
                            )
                        )
                        known |= {str(e) for e in (pf.get("evidence_ids") or [])}
                    # P1/2.2：结构化结果记录
                    from paperlens_core.documents import Asset as AssetIR
                    from paperlens_core.experiments import extract_result_records

                    assets = [
                        AssetIR.model_validate(item)
                        for item in repository.load_document(version.version_id, "assets")
                    ]
                    records = [
                        record.model_dump(mode="json")
                        for record in extract_result_records(assets)
                    ][:40]
                    return {
                        "index": index,
                        "version_id": version.version_id,
                        "cells": cells,
                        "known": known,
                        "records": records,
                    }
                except Exception as exc:  # P4/3.4：单篇失败降级
                    logger.warning(
                        "comparison paper %s extraction failed: %s", version.version_id, exc
                    )
                    degraded = [
                        ComparisonCell(
                            paper_id=version.version_id,
                            field=field,
                            status=CoverageStatus.UNASSESSABLE_PARSE_GAP,
                            note=f"该论文抽取失败（{type(exc).__name__}），无法参与该字段比较。",
                        )
                        for field in fields
                    ]
                    return {
                        "index": index,
                        "version_id": version.version_id,
                        "cells": degraded,
                        "known": set(),
                        "records": [],
                    }

            extracted_results: list[dict[str, object]] = []
            with _TPE(max_workers=min(len(versions), 3)) as pool:
                futures = [
                    pool.submit(extract_paper, version, index)
                    for index, version in enumerate(versions)
                ]
                for done_count, future in enumerate(as_completed(futures), start=1):
                    extracted_results.append(future.result())
                    progress = round(done_count / len(versions), 2)
                    repository.save_comparison(
                        comparison_id,
                        {
                            "comparison_id": comparison_id,
                            "status": "RUNNING",
                            "stage": f"抽取完成 {done_count}/{len(versions)} 篇",
                            "progress": progress,
                            "paper_version_ids": request.paper_version_ids,
                        },
                    )

            extracted: list[ComparisonCell] = []
            evidence: dict[str, set[str]] = {}
            summaries: list[dict[str, str]] = []
            records_by_paper: dict[str, list[dict[str, object]]] = {}
            cells_by_paper: dict[str, list[ComparisonCell]] = {}
            for result in sorted(extracted_results, key=lambda item: int(item["index"])):
                version_id = str(result["version_id"])
                cells = result["cells"]
                extracted.extend(cells)
                evidence[version_id] = result["known"]
                cells_by_paper[version_id] = cells
                records_by_paper[version_id] = result["records"]
                summaries.append(
                    {
                        "paper_id": version_id,
                        "task": _cell_value(cells, "task_definition"),
                        "method": _cell_value(cells, "method_core"),
                        "metrics": _cell_value(cells, "metrics"),
                    }
                )

            # P0/2.1：对齐输入 = 本次抽取 cells（拒绝空摘要）
            if not any(
                p.get("task") or p.get("method") or p.get("metrics") for p in summaries
            ):
                alignment = type(
                    "TopicAlignmentResult",
                    (),
                    {
                        "alignment": "RELATED",
                        "rationale": "各论文均无法完成抽取（解析或模型失败），"
                        "无法判定任务可比性，保守标记为仅可方法对照。",
                        "confidence": 0.1,
                        "evidence_fields": [],
                    },
                )
            else:
                alignment = judge_topic_alignment(
                    model=model, papers=summaries, thread_id="compare-" + comparison_id
                )
            table = assemble_comparison(
                [version.version_id for version in versions],
                extracted,
                fields=fields,
                known_evidence=evidence,
            )
            table = add_comparability_warnings(table, alignment=alignment.alignment)
            result_comparisons = build_result_comparisons(records_by_paper)
            result = {
                "comparison_id": comparison_id,
                "status": "DONE",
                "paper_version_ids": request.paper_version_ids,
                "alignment": {
                    "alignment": alignment.alignment,
                    "rationale": alignment.rationale,
                    "confidence": getattr(alignment, "confidence", 0.5),
                    "evidence_fields": getattr(alignment, "evidence_fields", []),
                },
                "table": table.model_dump(mode="json"),
                "result_comparisons": [
                    group.model_dump(mode="json") for group in result_comparisons
                ],
                "cells_by_paper": {
                    paper_id: [cell.model_dump(mode="json") for cell in cells]
                    for paper_id, cells in cells_by_paper.items()
                },
                "fields": fields,  # 审计 P1：缓存 key 用（2026-08-05）
                # 2026-08-06：单元格中文翻译（一次 LLM 批量调用，失败降级）
                "cell_translations": translate_comparison_cells(model, extracted),
                "created_at": now_iso(),
            }
            repository.save_comparison(comparison_id, result)
            bus.publish(
                comparison_id,
                {
                    "event": "comparison_done",
                    "comparison_id": comparison_id,
                    "alignment": result["alignment"]["alignment"],
                },
            )
        except Exception as exc:  # noqa: BLE001 - record failure
            logger.error("comparison %s failed: %s", comparison_id, exc, exc_info=True)
            repository.save_comparison(
                comparison_id,
                {
                    "comparison_id": comparison_id,
                    "status": "FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                    "paper_version_ids": request.paper_version_ids,
                },
            )
            bus.publish(
                comparison_id,
                {
                    "event": "comparison_failed",
                    "comparison_id": comparison_id,
                    "error": str(exc)[:200],
                },
            )

    # 立即持久化初始 RUNNING 记录（修复 2026-08-05）：此前 run() 完成前
    # GET /comparisons/{id} 会 404，前端首次轮询把 comparison_id 覆盖成
    # undefined，之后永远轮询 /comparisons/undefined "卡住不动"
    repository.save_comparison(
        comparison_id,
        {
            "comparison_id": comparison_id,
            "status": "RUNNING",
            "stage": "正在准备…",
            "progress": 0.0,
            "paper_version_ids": request.paper_version_ids,
            "created_at": now_iso(),
        },
    )

    import threading

    threading.Thread(target=run, daemon=True).start()
    return {
        "comparison_id": comparison_id,
        "status": "RUNNING",
        "paper_version_ids": request.paper_version_ids,
    }


@app.get("/api/v1/comparisons")
def list_comparisons(limit: int = Query(default=10, ge=1, le=50)) -> list[dict[str, object]]:
    """V4.7（审计 P2/1.5）：比较历史列表。"""
    return repository.list_comparisons(limit)


@app.get("/api/v1/comparisons/{comparison_id}/events")
async def comparison_events(comparison_id: str) -> StreamingResponse:
    """V4.7（审计 P2/3.3）：比较进度 SSE。"""
    return StreamingResponse(
        bus.stream(comparison_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/v1/comparisons/{comparison_id}")
def get_comparison(comparison_id: str) -> dict[str, object]:
    row = repository.load_comparison(comparison_id)
    if row is None:
        raise HTTPException(404, "comparison not found")
    return row


@app.post("/api/v1/comparisons/{comparison_id}/questions")
def ask_comparison_question(comparison_id: str, request: ComparisonQuestion) -> dict[str, object]:
    """V4.7（审计 P2/3.3 + P4/1.5）：跨论文问答——只基于各篇已抽取的
    cells 与证据引文作答，不重复读取论文。"""
    comparison = repository.load_comparison(comparison_id)
    if comparison is None:
        raise HTTPException(404, "comparison not found")
    if comparison.get("status") != "DONE":
        raise HTTPException(409, "comparison is not finished")
    from paperlens_core.comparison import ComparisonCell, answer_cross_paper_question
    from paperlens_core.config import Settings
    from paperlens_core.llm import OpenAICompatibleModel

    cells_by_paper: dict[str, list[ComparisonCell]] = {}
    for paper_id, cells in (comparison.get("cells_by_paper") or {}).items():
        cleaned: list[ComparisonCell] = []
        for item in cells:
            try:
                cleaned.append(ComparisonCell.model_validate(item))
            except Exception:  # 旧数据可能超出上限，截断重试
                item = dict(item)
                item["evidence_ids"] = item.get("evidence_ids", [])[:6]
                item["quotes"] = item.get("quotes", [])[:9]
                item["locators"] = item.get("locators", [])[:9]
                cleaned.append(ComparisonCell.model_validate(item))
        cells_by_paper[paper_id] = cleaned
    answer = answer_cross_paper_question(
        model=OpenAICompatibleModel(Settings()),
        question=request.question,
        cells_by_paper=cells_by_paper,
        thread_id="compare-qa-" + comparison_id,
        history=request.history,
        # 2026-08-06：问答默认使用中文（比较时生成的单元格翻译）
        cell_translations=comparison.get("cell_translations") or {},
    )
    return {
        "question": request.question,
        "answer": answer.model_dump(mode="json"),
    }


@app.get("/api/v1/comparisons/{comparison_id}/export")
def export_comparison(comparison_id: str) -> Response:
    """V4.7（审计 P2/3.3）：Markdown 导出。"""
    comparison = repository.load_comparison(comparison_id)
    if comparison is None:
        raise HTTPException(404, "comparison not found")
    table = comparison.get("table") or {}
    lines = [
        f"# PaperLens 多篇比较 {comparison_id}",
        "",
        f"- 可比性：{comparison.get('alignment', {}).get('alignment')}（置信度 "
        f"{comparison.get('alignment', {}).get('confidence', '—')}）",
        f"- 依据：{comparison.get('alignment', {}).get('rationale', '')}",
        "",
        "## 对比矩阵",
        "",
    ]
    paper_ids = table.get("paper_ids") or []
    lines.append("| 字段 | " + " | ".join(paper_ids) + " |")
    lines.append("| --- | " + " | ".join("---" for _ in paper_ids) + " |")
    cells = table.get("cells") or []
    for field in table.get("fields") or []:
        row = [field]
        for pid in paper_ids:
            cell = next(
                (c for c in cells if c.get("paper_id") == pid and c.get("field") == field), {}
            )
            row.append(str(cell.get("value") or cell.get("note") or "未找到"))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("## 结构化结果对比")
    lines.append("")
    for group in (comparison.get("result_comparisons") or []):
        flag = "✅ 可比" if group.get("same_key") else "⚠️ Not directly comparable"
        lines.append(
            f"- **{group.get('dataset')} · {group.get('metric')}**（{flag}）："
            + "；".join(
                f"{pid}={value}" for pid, value in (group.get("values") or {}).items()
            )
        )
    lines.append("")
    lines.append(f"生成时间：{comparison.get('created_at', '')}")
    return Response(
        content="\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{comparison_id}.md"'},
    )


# --------------------------------------------------------------------------
# TaskDefinitions（V4.3-3）：服务端版本化任务定义
# --------------------------------------------------------------------------
@app.get("/api/tasks")
def list_tasks() -> dict[str, object]:
    from paperlens_core.tasks import TASK_DEFINITIONS

    return {"definitions": TASK_DEFINITIONS}


# --------------------------------------------------------------------------
# Translation (P3): glossary once, batch translate per page/section, verify.
# --------------------------------------------------------------------------
@app.post("/api/papers/{paper_id}/translations")
def translate_paper(paper_id: str, request: TranslateRequest) -> dict[str, object]:
    version = _pick_version(paper_id, "")
    from paperlens_core.config import Settings
    from paperlens_core.llm import OpenAICompatibleModel
    from paperlens_core.translation import (
        batch_translate,
        build_glossary,
        make_units,
    )

    settings = Settings()
    model = OpenAICompatibleModel(settings)
    thread_id = f"translate-{version.version_id}"

    # existing units (cache); rebuild only the requested page if needed.
    # NEEDS_RETRY units are not done: they re-enter pending so page requests
    # actually retry them (fix 2026-08-04)
    units = [TranslationUnit.model_validate(item) for item in repository.load_document(version.version_id, "translations")]
    unit_by_block = {unit.source_block_ids[0]: unit for unit in units if unit.source_block_ids}
    blocks = [Block.model_validate(item) for item in repository.load_document(version.version_id, "blocks")]
    requested_pages = request.pages or ([request.page] if request.page is not None else None)
    if requested_pages is not None:
        blocks = [block for block in blocks if block.page in set(requested_pages)]
    text_blocks = [
        block for block in blocks
        if block.block_type == BlockType.TEXT
        and block.text.strip()
        and len(block.text) > 40
        # V3.22：HTML 公式块的 block_type 是 TEXT，角色在 metadata——
        # 公式不需要翻译，也不该占用翻译队列
        and (block.metadata or {}).get("html_role") != "FORMULA"
    ]
    # V3.22：block_id 是索引型，重解析后同 id 内容会变——旧翻译单元必须
    # 按内容校验，错位的作废重译
    from paperlens_core.translation import unit_matches_block

    block_texts = {block.block_id: block.text for block in text_blocks}
    existing = {
        block_id
        for block_id, unit in unit_by_block.items()
        if unit.status != TranslationStatus.NEEDS_RETRY
        and unit_matches_block(unit.source_text, block_texts.get(block_id, ""))
    }
    if request.section_id is not None:
        text_blocks = [block for block in text_blocks if block.section_id == request.section_id]
    text_blocks.sort(key=lambda block: (block.page, block.paragraph_index))

    # NEEDS_RETRY units are not "done": they re-enter the pending set so the
    # workbench's page requests actually retry them (fix 2026-08-04)
    pending = [
        block for block in text_blocks
        if block.block_id not in existing or request.rebuild
    ]
    if not pending:
        return {"translated": 0, "cached": len(text_blocks), "units": len(units)}

    from paperlens_core.translation import (
        GlossaryEntry,
        PaperTranslationProfile,
        build_profile,
        terminology_concordance,
    )

    # glossary: build once from abstract + method (cached per version)
    glossary: list[dict[str, object]] = []
    glossary_cache = repository.load_document(version.version_id, "glossary")
    if glossary_cache:
        glossary = [json.loads(item) for item in glossary_cache] if isinstance(glossary_cache[0], str) else glossary_cache
    else:
        abstract_texts = [
            block.text for block in blocks if block.page <= 2 and block.text.strip()
        ][:6]
        entries = build_glossary(model, abstract_texts, thread_id=thread_id)
        glossary = [entry.model_dump(mode="json") for entry in entries]
        repository.store_document(version.version_id, "glossary", glossary)
    glossary_entries = [GlossaryEntry.model_validate(entry) for entry in glossary]

    section_map = {
        section.section_id: section
        for section in [Section.model_validate(item) for item in repository.load_document(version.version_id, "sections")]
    }

    # full-document view for profile/briefs (blocks may be page-filtered above)
    all_blocks = [
        Block.model_validate(item)
        for item in repository.load_document(version.version_id, "blocks")
    ]

    # PaperTranslationProfile: structured, versioned, shared by all batches
    #  — built once per version, cached like the glossary.
    profile_cache = repository.load_document(version.version_id, "translation_profile")
    profile: PaperTranslationProfile | None = None
    if profile_cache and isinstance(profile_cache[0], dict):
        profile = PaperTranslationProfile.model_validate(profile_cache[0])
    else:
        section_titles = [section.title for section in section_map.values() if section.title]
        captions = [
            block.text for block in all_blocks
            if block.block_type == BlockType.CAPTION and block.text.strip()
        ]
        abstract = "\n".join(
            block.text for block in all_blocks if block.page <= 1 and block.text.strip()
        )[:2000]
        try:
            profile = build_profile(
                model,
                title=version.file_name,
                abstract=abstract,
                section_titles=section_titles,
                captions=captions,
                thread_id=thread_id,
            )
            repository.store_document(
                version.version_id,
                "translation_profile",
                [profile.model_dump(mode="json")],
            )
        except Exception:  # noqa: BLE001 - profile is an enhancement, never fatal
            profile = None

    # deterministic per-section briefs (§13.1 level 3): title + first paragraph
    section_briefs: dict[str, str] = {}
    for section_id, section in section_map.items():
        first = next(
            (
                block.text for block in all_blocks
                if block.section_id == section_id
                and block.block_type == BlockType.TEXT
                and block.text.strip()
            ),
            "",
        )
        brief = (section.title + " — " + first) if first else section.title
        section_briefs[section_id] = brief[:300]

    def _context_blocks(start: int) -> list[str]:
        """§13.1 levels 4-5: previous 1-2 paragraphs + next 1, understanding only."""
        previous = pending[max(0, start - 2) : start]
        following = pending[start + 6 : start + 7]
        return [block.text for block in previous] + [block.text for block in following]

    # batch translate in groups of 6 paragraphs, concurrent across batches.
    # The model client is not thread-safe per call, so each worker gets its own
    # OpenAICompatibleModel instance.
    from concurrent.futures import ThreadPoolExecutor

    def translate_group(start: int) -> list[TranslationUnit]:
        group = pending[start : start + 6]
        section = section_map.get(group[0].section_id)
        section_title = section.title if section else ""
        worker_model = OpenAICompatibleModel(Settings())
        targets, issues = batch_translate(
            worker_model,
            paragraphs=[block.text for block in group],
            section_title=section_title,
            previous_summary="",
            glossary=glossary_entries,
            thread_id=thread_id,
            profile=profile,
            section_brief=section_briefs.get(group[0].section_id, ""),
            context_blocks=_context_blocks(start),
        )
        return make_units(
            paper_version_id=version.version_id,
            section_id=group[0].section_id,
            source_blocks=[block.model_dump(mode="json") for block in group],
            targets=targets,
            issues=issues,
            model_name=settings.paperlens_model,
            thread_id=thread_id,
        )

    batches = list(range(0, len(pending), 6))
    # V4.6-5（检查 4）：翻译逐条显示——批次完成即持久化（as_completed），
    # 前端轮询 /translations 时译文逐批出现，而非全部完成后一次性返回
    from concurrent.futures import as_completed as _as_completed

    new_units: list[object] = []
    with _TRANSLATE_SEMAPHORE:
        with ThreadPoolExecutor(max_workers=min(4, len(batches) or 1)) as pool:
            futures = {pool.submit(translate_group, batch): batch for batch in batches}
            for future in _as_completed(futures):
                new_units.extend(future.result())
                fresh_ids = {
                    unit.source_block_ids[0] for unit in new_units if unit.source_block_ids
                }
                progressive = [
                    unit.model_dump(mode="json")
                    for unit in units
                    if not request.rebuild
                    and (
                        not unit.source_block_ids
                        or unit.source_block_ids[0] not in fresh_ids
                    )
                ]
                progressive.extend(
                    unit.model_dump(mode="json") for unit in new_units
                )
                repository.store_document(version.version_id, "translations", progressive)

    # terminology concordance + selective repair (§15.2): only units that
    # drifted from the glossary are re-translated, never the whole paper
    findings = terminology_concordance(new_units, glossary_entries)
    if findings:
        flagged_ids = {
            block_id
            for finding in findings
            for block_id in finding["source_block_ids"]
        }
        instructions: dict[str, list[str]] = {}
        for finding in findings:
            for block_id in finding["source_block_ids"]:
                instructions.setdefault(block_id, []).extend(finding["violations"])
        flagged_blocks = [block for block in pending if block.block_id in flagged_ids]
        unit_by_block = {unit.source_block_ids[0]: unit for unit in new_units}
        for start in range(0, len(flagged_blocks), 6):
            group = flagged_blocks[start : start + 6]
            section = section_map.get(group[0].section_id)
            worker_model = OpenAICompatibleModel(Settings())
            targets, _ = batch_translate(
                worker_model,
                paragraphs=[block.text for block in group],
                section_title=section.title if section else "",
                previous_summary="",
                glossary=glossary_entries,
                thread_id=thread_id,
                profile=profile,
                section_brief=section_briefs.get(group[0].section_id, ""),
                repair_instructions=[
                    "；".join(instructions.get(block.block_id, [])) for block in group
                ],
            )
            for block, target in zip(group, targets, strict=True):
                unit = unit_by_block.get(block.block_id)
                if unit is not None and target:
                    unit.target_text = target
                    unit.alignment = {**unit.alignment, "repaired": True}

    # V3.22：unit_id 按 block_id 派生（确定性），本轮重译的块要剔除旧单元，
    # 否则文档里出现同 unit_id 双份（前端 map.set 后者覆盖虽对，但留垃圾）
    fresh_block_ids = {
        unit.source_block_ids[0] for unit in new_units if unit.source_block_ids
    }
    merged = [
        unit.model_dump(mode="json")
        for unit in units
        if not request.rebuild
        and (not unit.source_block_ids or unit.source_block_ids[0] not in fresh_block_ids)
    ]
    merged.extend(unit.model_dump(mode="json") for unit in new_units)
    repository.store_document(version.version_id, "translations", merged)
    from collections import Counter as _Counter

    statuses = _Counter(unit.status.value for unit in new_units)
    logger.info(
        "translate %s pages=%s: translated=%d cached=%d %s",
        version.version_id[-10:],
        requested_pages,
        len(new_units),
        len(units),
        dict(statuses),
    )
    return {"translated": len(new_units), "cached": len(units), "units": len(merged)}


@app.get("/api/papers/{paper_id}/translations")
def get_translations(paper_id: str, page: int | None = None) -> list[dict[str, object]]:
    version = _pick_version(paper_id, "")
    units = [TranslationUnit.model_validate(item) for item in repository.load_document(version.version_id, "translations")]
    if page is not None:
        blocks = [Block.model_validate(item) for item in repository.load_document(version.version_id, "blocks")]
        page_blocks = {block.block_id for block in blocks if block.page == page}
        units = [unit for unit in units if unit.source_block_ids and unit.source_block_ids[0] in page_blocks]
    return [unit.model_dump(mode="json") for unit in units]


# --------------------------------------------------------------------------
# Analyses
# --------------------------------------------------------------------------
@app.post("/api/papers/{paper_id}/analyses/cv-profile")
def run_cv_profile(paper_id: str, version_id: str = Query(default="")) -> dict[str, object]:
    version = _pick_version(paper_id, version_id)
    # V4.3-2：UnderstandingArtifact 版本化持久化——重复构建直接返回缓存
    persisted = repository.load_document(version.version_id, "understanding_artifact")
    if persisted:
        return persisted[0]
    chunks = [Chunk.model_validate(item) for item in repository.load_document(version.version_id, "chunks")]
    from paperlens_core.config import Settings
    from paperlens_core.cv_profile import CVProfileBuilder, UnderstandingArtifact
    from paperlens_core.llm import OpenAICompatibleModel

    settings = Settings()
    profile = CVProfileBuilder(OpenAICompatibleModel(settings)).build(
        chunks=chunks, paper_id=paper_id, thread_id="cv-profile-" + paper_id
    )
    from .repository import now_iso

    artifact = UnderstandingArtifact(
        artifact_id=f"ua-{version.version_id[:10]}-{uuid.uuid4().hex[:8]}",
        paper_version_id=version.version_id,
        generated_at=now_iso(),
        profile=profile,
    )
    repository.store_document(
        version.version_id,
        "understanding_artifact",
        [artifact.model_dump(mode="json")],
    )
    return artifact.model_dump(mode="json")


@app.post("/api/papers/{paper_id}/analyses/quality")
def run_quality(paper_id: str, version_id: str = Query(default="")) -> dict[str, object]:
    version = _pick_version(paper_id, version_id)
    # V4.1：DocumentGraph 统一——documents.Chunk 直接进 reader/档案构建，
    # 不再经 _legacy_chunks 桥接
    chunks = [Chunk.model_validate(item) for item in repository.load_document(version.version_id, "chunks")]
    from paperlens_core.config import Settings
    from paperlens_core.llm import OpenAICompatibleModel

    settings = Settings()
    assessment = QualityAgent(OpenAICompatibleModel(settings)).assess(
        chunks=chunks, paper_id=paper_id, thread_id="quality-" + paper_id
    )
    return assessment.model_dump(mode="json")


# --------------------------------------------------------------------------
# Annotations (Notes)
# --------------------------------------------------------------------------
@app.post("/api/papers/{paper_id}/annotations")
def save_annotation(paper_id: str, request: AnnotationRequest, user_id: str = "guest") -> dict[str, str]:
    version = _pick_version(paper_id, "")
    annotation = Annotation(
        annotation_id=f"ant-{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        paper_version_id=version.version_id,
        block_id=request.block_id,
        char_start=request.char_start,
        char_end=request.char_end,
        kind=request.kind,
        text=request.text,
        created_at=now_iso(),
    )
    repository.save_annotation(annotation)
    return {"annotation_id": annotation.annotation_id}


@app.get("/api/papers/{paper_id}/annotations")
def list_annotations(paper_id: str, user_id: str = "guest") -> list[dict[str, object]]:
    version = _pick_version(paper_id, "")
    return repository.list_annotations(user_id, version.version_id)


@app.get("/api/health")
def health() -> dict[str, str]:
    # V4.0-6：版本号统一入口（core/paperlens_core/version.py）
    from paperlens_core.version import ARCH_GENERATION, __version__

    return {"status": "ok", "version": __version__, "generation": ARCH_GENERATION}
