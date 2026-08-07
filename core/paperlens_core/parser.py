"""Coordinate-aware PDF parsing with explicit media placeholders."""

from __future__ import annotations

import io
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from importlib.metadata import version
from statistics import median
from typing import Any

import pdfplumber

from .models import Block, BlockType, CleaningEvent, Paper
from .utils import normalize_match_text, normalize_space, sha256_bytes, sha256_text


class PDFValidationError(ValueError):
    """Raised for a user-correctable PDF input problem."""


@dataclass(slots=True)
class ParsedDocument:
    paper: Paper
    blocks: list[Block]
    cleaning_events: list[CleaningEvent]


def validate_pdf(data: bytes, *, max_mb: int = 80) -> None:
    if not data:
        raise PDFValidationError("文件为空。")
    if len(data) > max_mb * 1024 * 1024:
        raise PDFValidationError(f"PDF 超过 {max_mb} MiB 限制。")
    if not data.lstrip().startswith(b"%PDF-"):
        raise PDFValidationError("文件头不是 PDF；请上传原始 .pdf 文件。")


def _line_records(words: list[dict[str, Any]], y_tolerance: float = 3.0) -> list[dict[str, Any]]:
    """Group word records into lines while retaining geometry and font signals."""

    groups: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"]))):
        top = float(word["top"])
        target: list[dict[str, Any]] | None = None
        for group in reversed(groups[-5:]):
            group_top = sum(float(item["top"]) for item in group) / len(group)
            if abs(group_top - top) <= y_tolerance:
                target = group
                break
            if group_top < top - y_tolerance:
                break
        if target is None:
            target = []
            groups.append(target)
        target.append(word)

    lines: list[dict[str, Any]] = []
    for group in groups:
        ordered = sorted(group, key=lambda item: float(item["x0"]))
        # Words sharing a y coordinate can still belong to opposite columns.
        # Split at a large x gap before detecting reading order, otherwise a
        # left-column heading may be joined to right-column prose.
        segments: list[list[dict[str, Any]]] = [[]]
        for word in ordered:
            if segments[-1]:
                gap = float(word["x0"]) - float(segments[-1][-1]["x1"])
                if gap > 12:
                    segments.append([])
            segments[-1].append(word)
        refined_segments: list[list[dict[str, Any]]] = []
        for segment in segments:
            first_text = str(segment[0].get("text", "")).casefold().rstrip(":：")
            if first_text in {"abstract", "摘要"} and len(segment) > 1:
                refined_segments.extend(([segment[0]], segment[1:]))
            else:
                refined_segments.append(segment)
        for segment in refined_segments:
            text = normalize_space(" ".join(str(item.get("text", "")) for item in segment))
            if not text:
                continue
            sizes = [float(item.get("size") or 0) for item in segment if item.get("size")]
            fonts = [str(item.get("fontname") or "") for item in segment]
            lines.append(
                {
                    "text": text,
                    "x0": min(float(item["x0"]) for item in segment),
                    "top": min(float(item["top"]) for item in segment),
                    "x1": max(float(item["x1"]) for item in segment),
                    "bottom": max(float(item["bottom"]) for item in segment),
                    "font_size": median(sizes) if sizes else None,
                    "is_bold": bool(fonts)
                    and sum("bold" in font.casefold() for font in fonts) >= len(fonts) / 2,
                }
            )
    return lines


def _reading_order(lines: list[dict[str, Any]], width: float) -> list[dict[str, Any]]:
    """Order one- or two-column academic pages deterministically."""

    if len(lines) < 8:
        return sorted(lines, key=lambda item: (item["top"], item["x0"]))
    center = width / 2
    left = [line for line in lines if line["x1"] < center + width * 0.03]
    right = [line for line in lines if line["x0"] > center - width * 0.03]
    crossing = [line for line in lines if line not in left and line not in right]
    narrow_crossing = [line for line in crossing if (line["x1"] - line["x0"]) < width * 0.60]
    is_two_column = len(left) >= 4 and len(right) >= 4 and len(narrow_crossing) <= len(lines) * 0.25
    if not is_two_column:
        return sorted(lines, key=lambda item: (item["top"], item["x0"]))

    # Full-width matter is anchored by y. Column lines between two anchors are read L->R.
    anchors = sorted(crossing, key=lambda item: item["top"])
    ordered: list[dict[str, Any]] = []
    lower = -math.inf
    for anchor in anchors + [{"top": math.inf}]:
        upper = float(anchor["top"])
        ordered.extend(
            sorted([x for x in left if lower <= x["top"] < upper], key=lambda x: x["top"])
        )
        ordered.extend(
            sorted([x for x in right if lower <= x["top"] < upper], key=lambda x: x["top"])
        )
        if upper != math.inf:
            ordered.append(anchor)
        lower = upper
    return ordered


def _formula_like(text: str) -> bool:
    if len(text) < 5 or len(text) > 240:
        return False
    math_symbols = len(re.findall(r"[=∑∏∫√±×÷≤≥≈∞α-ωΑ-Ω_^{}|]", text))
    words = len(re.findall(r"[A-Za-z]{3,}", text))
    return math_symbols >= 2 and math_symbols * 5 >= len(text) and words <= 3


def _remove_repeated_marginalia(
    page_blocks: dict[int, list[Block]], page_heights: dict[int, float], paper_id: str
) -> tuple[list[Block], list[CleaningEvent]]:
    page_count = len(page_blocks)
    occurrences: dict[str, set[int]] = defaultdict(set)
    candidates: dict[tuple[int, str], Block] = {}
    for page, blocks in page_blocks.items():
        height = page_heights[page]
        for block in blocks:
            if block.block_type != BlockType.TEXT or len(block.text) > 100:
                continue
            is_margin = block.bbox[1] <= height * 0.08 or block.bbox[3] >= height * 0.92
            key = normalize_match_text(re.sub(r"\b\d+\b", "#", block.text))
            if is_margin and key:
                occurrences[key].add(page)
                candidates[(page, key)] = block
    threshold = max(2, math.ceil(page_count * 0.60))
    repeated = {key for key, pages in occurrences.items() if len(pages) >= threshold}
    events: list[CleaningEvent] = []
    kept: list[Block] = []
    for page, blocks in page_blocks.items():
        for block in blocks:
            key = normalize_match_text(re.sub(r"\b\d+\b", "#", block.text))
            if key in repeated and (page, key) in candidates:
                events.append(
                    CleaningEvent(
                        paper_id=paper_id,
                        event_type="REMOVE_REPEATED_HEADER_FOOTER",
                        page=page,
                        detail=block.text[:160],
                    )
                )
            else:
                kept.append(block)
    return kept, events


def _infer_title(blocks: list[Block]) -> str:
    """Return a conservative first-page title candidate; never use model memory."""

    candidates = [
        block
        for block in blocks
        if block.page == 1
        and block.block_type == BlockType.TEXT
        and 4 <= len(block.text) <= 240
        and normalize_match_text(block.text)
        not in {"abstract", "introduction", "preprint", "submitted", "accepted"}
        and not re.fullmatch(r"\d+", block.text.strip())
    ]
    if not candidates:
        return ""
    sizes = [block.font_size or 0 for block in candidates]
    largest = max(sizes)
    if largest <= 0:
        return candidates[0].text
    title_lines = [
        block
        for block in candidates
        if (block.font_size or 0) >= largest * 0.92
        and block.bbox[1] < block.metadata.get("page_height", 9999) * 0.45
    ]
    title_lines.sort(key=lambda block: (block.bbox[1], block.bbox[0]))
    return normalize_space(" ".join(block.text for block in title_lines[:3]))


def parse_pdf_bytes(data: bytes, file_name: str, *, max_mb: int = 80) -> ParsedDocument:
    """Parse a born-digital PDF into line/media blocks with page coordinates."""

    validate_pdf(data, max_mb=max_mb)
    digest = sha256_bytes(data)
    paper_id = digest[:16]
    page_blocks: dict[int, list[Block]] = defaultdict(list)
    page_heights: dict[int, float] = {}
    events: list[CleaningEvent] = []

    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:  # pdf backends expose several exception types
        raise PDFValidationError(f"PDF 无法打开：{exc}") from exc

    try:
        if not pdf.pages:
            raise PDFValidationError("PDF 没有可读取页面。")
        for page_number, page in enumerate(pdf.pages, start=1):
            page_heights[page_number] = float(page.height)
            try:
                words = page.extract_words(
                    x_tolerance=2,
                    y_tolerance=3,
                    keep_blank_chars=False,
                    use_text_flow=False,
                    extra_attrs=["fontname", "size"],
                )
            except Exception as exc:
                events.append(
                    CleaningEvent(
                        paper_id=paper_id,
                        event_type="PAGE_TEXT_EXTRACTION_FAILED",
                        page=page_number,
                        detail=str(exc)[:300],
                    )
                )
                words = []
            lines = [
                line
                for line in _line_records(words)
                if line["x1"] > 0
                and line["x0"] < float(page.width)
                and line["bottom"] > 0
                and line["top"] < float(page.height)
            ]
            lines = _reading_order(lines, float(page.width))
            page_font_sizes = [line["font_size"] for line in lines if line["font_size"]]
            body_size = median(page_font_sizes) if page_font_sizes else None
            block_index = 0
            for line in lines:
                block_type = BlockType.FORMULA if _formula_like(line["text"]) else BlockType.TEXT
                text = line["text"]
                if block_type == BlockType.FORMULA:
                    text = f"⟦FORMULA p.{page_number} b.{block_index}⟧ {text}"
                block_id = f"{paper_id}:p{page_number}:b{block_index}"
                page_blocks[page_number].append(
                    Block(
                        block_id=block_id,
                        paper_id=paper_id,
                        paper_version_id="",  # V4.1: to_blocks 以 version 补全
                        page=page_number,
                        block_index=block_index,
                        bbox=(line["x0"], line["top"], line["x1"], line["bottom"]),
                        block_type=block_type,
                        text=text,
                        font_size=line["font_size"],
                        is_bold=line["is_bold"],
                        content_sha256=sha256_text(text),
                        metadata={
                            "page_width": float(page.width),
                            "page_height": float(page.height),
                            "body_font_size": body_size,
                        },
                    )
                )
                block_index += 1

            # Media objects are never silently dropped. Their coordinates remain auditable.
            for image in page.images:
                bbox = (
                    float(image.get("x0", 0)),
                    float(image.get("top", 0)),
                    float(image.get("x1", page.width)),
                    float(image.get("bottom", page.height)),
                )
                rounded_bbox = tuple(round(x, 1) for x in bbox)
                text = f"⟦FIGURE p.{page_number} b.{block_index} bbox={rounded_bbox}⟧"
                page_blocks[page_number].append(
                    Block(
                        block_id=f"{paper_id}:p{page_number}:b{block_index}",
                        paper_id=paper_id,
                        paper_version_id="",  # V4.1: to_blocks 以 version 补全
                        page=page_number,
                        block_index=block_index,
                        bbox=bbox,
                        block_type=BlockType.FIGURE,
                        text=text,
                        content_sha256=sha256_text(text),
                        metadata={"object_name": image.get("name", "")},
                    )
                )
                block_index += 1

            try:
                tables = page.find_tables()
            except Exception as exc:
                events.append(
                    CleaningEvent(
                        paper_id=paper_id,
                        event_type="TABLE_DETECTION_FAILED",
                        page=page_number,
                        detail=str(exc)[:300],
                    )
                )
                tables = []
            for table in tables:
                bbox = tuple(float(x) for x in table.bbox)
                rounded_bbox = tuple(round(x, 1) for x in bbox)
                text = f"⟦TABLE p.{page_number} b.{block_index} bbox={rounded_bbox}⟧"
                page_blocks[page_number].append(
                    Block(
                        block_id=f"{paper_id}:p{page_number}:b{block_index}",
                        paper_id=paper_id,
                        paper_version_id="",  # V4.1: to_blocks 以 version 补全
                        page=page_number,
                        block_index=block_index,
                        bbox=bbox,
                        block_type=BlockType.TABLE,
                        text=text,
                        content_sha256=sha256_text(text),
                    )
                )
                block_index += 1
    finally:
        pdf.close()

    blocks, margin_events = _remove_repeated_marginalia(page_blocks, page_heights, paper_id)
    events.extend(margin_events)
    text_counts = Counter(
        block.page for block in blocks if block.block_type == BlockType.TEXT and block.text
    )
    sparse_pages = sum(text_counts.get(page, 0) <= 1 for page in page_blocks)
    status = "READY"
    if sparse_pages / max(1, len(page_blocks)) > 0.70:
        status = "PARTIAL"
        events.append(
            CleaningEvent(
                paper_id=paper_id,
                event_type="SCANNED_OR_BROKEN_SUSPECTED",
                detail="超过 70% 页面几乎没有可抽取文本；结果仅作部分解析。",
            )
        )
    paper = Paper(
        paper_id=paper_id,
        title=_infer_title(blocks),
        file_name=file_name,
        file_sha256=digest,
        page_count=len(page_blocks),
        parser_version=version("pdfplumber"),
        parse_status=status,
    )
    return ParsedDocument(paper=paper, blocks=blocks, cleaning_events=events)
