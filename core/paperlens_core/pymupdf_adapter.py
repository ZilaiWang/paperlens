"""PyMuPDF geometry adapter (V3.0B, 改进方案2.md §5-§6).

Replaces the pdfplumber word-then-fixed-gap line extraction with PyMuPDF
span-level extraction that keeps per-span font, size, bold and text
direction. Fixes the fragment-first problems:

- rotated text (vertical arXiv watermarks) is filtered out of the body;
- table regions (PyMuPDF find_tables) act as masks: their spans become
  TABLE_ROW blocks instead of polluting body paragraphs;
- spans keep their baseline so the paragraph rebuild merges math fragments
  on the same baseline.

The output uses the existing Block model so the downstream pipeline
(paragraph rebuild, sections, chunks) is unchanged.

AGPL note: PyMuPDF is AGPL-licensed; it is used as a geometry extractor in
this course project. The project's own code remains MIT.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .models import Block, BlockType

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None


@dataclass(slots=True)
class ExtractedSpan:
    text: str
    bbox: tuple[float, float, float, float]
    baseline: float
    font_size: float
    bold: bool
    direction: tuple[float, float] = (1.0, 0.0)
    in_table: bool = False
    table_index: int | None = None


def _span_flags_bold(flags: int) -> bool:
    return bool(flags & 2**4)  # PyMuPDF span flag bit 4 = bold


def _is_horizontal(direction: tuple[float, float], tolerance: float = 0.35) -> bool:
    return abs(direction[0]) >= 1 - tolerance


def extract_spans(page: Any) -> list[ExtractedSpan]:
    """Span-level extraction with font/direction; rotated spans are kept but
    flagged by direction so the caller can route them to marginalia."""
    spans: list[ExtractedSpan] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:  # 0 = text
            continue
        for line in block["lines"]:
            direction = tuple(line.get("dir", (1, 0)))
            for span in line["spans"]:
                text = span.get("text", "")
                if not text.strip():
                    continue
                bbox = tuple(span["bbox"])
                spans.append(
                    ExtractedSpan(
                        text=text,
                        bbox=bbox,
                        baseline=float(line.get("origin", (0, bbox[1]))[1]),
                        font_size=float(span.get("size", 10.0)),
                        bold=_span_flags_bold(int(span.get("flags", 0))),
                        direction=direction,
                    )
                )
    return spans


def mark_table_regions(page: Any, spans: list[ExtractedSpan]) -> list[tuple[float, float, float, float]]:
    """Spans inside a detected table bbox become table cells, not body text.

    Returns the detected table bboxes so the caller can emit TABLE placeholder
    blocks (审计 P0-5, 2026-08-05): previously table cells were masked from
    body paragraphs but no placeholder was produced, so table regions silently
    vanished from both text and assets.
    """
    try:
        tables = page.find_tables().tables
    except Exception:  # noqa: BLE001 - table detection is best-effort
        return []
    bboxes = [tuple(table.bbox) for table in tables]
    for table_index, table in enumerate(tables):
        x0, y0, x1, y1 = table.bbox
        for span in spans:
            sx0, sy0, sx1, sy1 = span.bbox
            if sx0 >= x0 - 1 and sx1 <= x1 + 1 and sy0 >= y0 - 1 and sy1 <= y1 + 1:
                span.in_table = True
                span.table_index = table_index
    return bboxes


def parse_pdf_bytes_pymupdf(raw: bytes, pdf_path: str) -> Any:
    """Parse with PyMuPDF; returns an object shaped like the legacy parser
    output (paper + blocks) so the rest of the pipeline is unchanged."""
    if fitz is None:
        raise RuntimeError("PyMuPDF not installed; install with: pip install pymupdf")
    document = fitz.open(stream=raw, filetype="pdf")
    blocks: list[Block] = []
    sha = hashlib.sha256(raw).hexdigest()
    paper_id = sha[:16]
    page_count = len(document)
    for page_index in range(page_count):
        page = document[page_index]
        width, height = page.rect.width, page.rect.height
        spans = extract_spans(page)
        table_bboxes = mark_table_regions(page, spans)
        page_blocks: list[Block] = []
        for span_index, span in enumerate(spans):
            # rotated text (vertical arXiv watermarks, chart labels on edge)
            # never enters the body stream
            if not _is_horizontal(span.direction):
                continue
            block_type = BlockType.TEXT  # table cells stay TEXT; flagged below
            page_blocks.append(
                Block(
                    block_id=f"{paper_id}:p{page_index + 1}:s{span_index}",
                    paper_id=paper_id,
                    # V4.1：解析阶段 paper_version_id 未知，to_blocks 补全
                    paper_version_id="",
                    page=page_index + 1,
                    block_index=span_index,
                    bbox=span.bbox,
                    block_type=block_type,
                    text=span.text,
                    font_size=span.font_size,
                    is_bold=span.bold,
                    content_sha256=hashlib.sha256(span.text.encode("utf-8")).hexdigest(),
                    metadata={
                        "page_width": width,
                        "page_height": height,
                        "baseline": span.baseline,
                        "direction": list(span.direction),
                        "rotated": not _is_horizontal(span.direction),
                        "table_cell": span.in_table,
                        "table_index": span.table_index,
                        "source_engine": "pymupdf",
                    },
                )
            )
        # 审计 P0-5：表格区域生成 TABLE 占位块（与 legacy pdfplumber 路径
        # 同格式，sections/assets 据此提取表格资产），并按 y 坐标插入流中
        for table_index, bbox in enumerate(table_bboxes):
            x0, y0, x1, y1 = bbox
            rounded_bbox = tuple(round(v, 1) for v in bbox)
            placeholder_index = sum(
                1 for block in page_blocks if block.bbox[1] < y0
            )
            text = (
                f"⟦TABLE p.{page_index + 1} b.{placeholder_index} "
                f"bbox={rounded_bbox}⟧"
            )
            page_blocks.insert(
                placeholder_index,
                Block(
                    block_id=f"{paper_id}:p{page_index + 1}:t{table_index}",
                    paper_id=paper_id,
                    paper_version_id="",
                    page=page_index + 1,
                    block_index=placeholder_index,
                    bbox=(x0, y0, x1, y1),
                    block_type=BlockType.TABLE,
                    text=text,
                    content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    metadata={
                        "page_width": width,
                        "page_height": height,
                        "source_engine": "pymupdf",
                    },
                )
            )
        for index, block in enumerate(page_blocks):
            blocks.append(block.model_copy(update={"block_index": index}))
    document.close()

    class _Parsed:
        pass

    parsed = _Parsed()
    parsed.paper = type(
        "Paper",
        (),
        {
            "paper_id": paper_id,
            "page_count": page_count,
            "file_sha256": sha,
            "title": "",
            "authors": [],
        },
    )()
    parsed.blocks = blocks
    return parsed
