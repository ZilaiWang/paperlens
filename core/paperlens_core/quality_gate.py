"""Deterministic per-page parse quality gate.

After parsing, each page gets a verdict instead of silently presenting
fragmented layout as correct output. The metrics are deterministic and
cheap: tiny-body-block ratio, table-text contamination, reading-order
inversions and character coverage. Pages failing the gate carry
fallback_reasons the UI can surface ("第 6 页：版面解析可信度较低…")
and future resolvers (Docling/PP-StructureV3) can re-run just those pages.

Scoring is deliberately conservative: any hard reason drops the page to
LOW, a single-char ratio above a soft threshold marks SUSPECT.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .documents import Block, BlockType

TINY_CHAR_LIMIT = 2
HARD_TINY_BLOCK_RATIO = 0.03
HARD_INVERSION_RATIO = 0.02
SOFT_SINGLE_CHAR_RATIO = 0.03
MIN_CHAR_COVERAGE = 150

_TABLE_CELL_RE = re.compile(
    r"^(?=[^a-z]*[A-Za-z]*[^a-z]*$)(?:[A-Za-z]{0,8}\s*)?\d+(?:\.\d+)?"
    r"(?:\s*(?:±|/|\+|-|–|—)\s*\d+(?:\.\d+)?)?(?:\s*%)?$"
)


def _looks_like_table_cell(text: str) -> bool:
    """True for short fragments dominated by numbers/symbols ("AP 50 75.3 ±0.2")."""
    stripped = text.strip()
    if not stripped or len(stripped) > 40:
        return False
    tokens = re.findall(r"\S+", stripped)
    if not tokens:
        return False
    numeric = sum(1 for token in tokens if re.match(r"^[±\-–—]?\d+(?:\.\d+)?%?$", token))
    return numeric / len(tokens) >= 0.6


def _count_inversions(text_blocks: list[Block], page_width: float) -> int:
    """Approximate reading-order inversions: same-column consecutive text
    blocks whose bbox moves upward (next.y0 < prev.y0 - tolerance)."""
    ordered = sorted(text_blocks, key=lambda block: (block.page, block.block_index))
    inversions = 0
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if current.bbox[1] >= previous.bbox[1] - 2.0:
            continue
        same_column = abs(current.bbox[0] - previous.bbox[0]) <= 15.0
        if same_column:
            inversions += 1
    return inversions


class PageQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int
    text_block_count: int
    single_char_ratio: float
    tiny_block_ratio: float
    table_contamination: int
    reading_order_inversions: int
    char_coverage: int
    verdict: Literal["GOOD", "SUSPECT", "LOW"]
    fallback_reasons: list[str] = Field(default_factory=list)
    # V4.2：Active Quality Gate 融合后记录本页最终
    # 采用的解析引擎（"pymupdf"/"pdfplumber"/"" = 主引擎未融合）
    resolved_by: str = ""

    @property
    def is_flagged(self) -> bool:
        return self.verdict != "GOOD"


def assess_page_quality(
    page: int,
    blocks: list[Block],
    *,
    page_width: float = 612.0,
) -> PageQuality:
    """Assess one page's blocks; empty pages pass as GOOD (nothing to show)."""
    text_blocks = [
        block for block in blocks
        if block.block_type == BlockType.TEXT and block.text.strip()
    ]
    total = len(text_blocks)
    if total == 0:
        return PageQuality(
            page=page,
            text_block_count=0,
            single_char_ratio=0.0,
            tiny_block_ratio=0.0,
            table_contamination=0,
            reading_order_inversions=0,
            char_coverage=0,
            verdict="GOOD",
            fallback_reasons=[],
        )
    single_chars = sum(1 for block in text_blocks if len(block.text.strip()) == 1)
    tiny = sum(1 for block in text_blocks if len(block.text.strip()) <= TINY_CHAR_LIMIT)
    contamination = sum(1 for block in text_blocks if _looks_like_table_cell(block.text))
    inversions = _count_inversions(text_blocks, page_width)
    coverage = sum(len(block.text) for block in text_blocks)

    reasons: list[str] = []
    if tiny / total > HARD_TINY_BLOCK_RATIO:
        reasons.append("TOO_MANY_TINY_BLOCKS")
    if contamination > 0:
        reasons.append("TABLE_TEXT_IN_BODY")
    if inversions > max(1, int(total * HARD_INVERSION_RATIO)):
        reasons.append("READING_ORDER_UNCERTAIN")
    if coverage < MIN_CHAR_COVERAGE:
        reasons.append("LOW_CHAR_COVERAGE")

    if reasons:
        verdict: Literal["GOOD", "SUSPECT", "LOW"] = "LOW"
    elif single_chars / total > SOFT_SINGLE_CHAR_RATIO:
        verdict = "SUSPECT"
    else:
        verdict = "GOOD"

    return PageQuality(
        page=page,
        text_block_count=total,
        single_char_ratio=round(single_chars / total, 4),
        tiny_block_ratio=round(tiny / total, 4),
        table_contamination=contamination,
        reading_order_inversions=inversions,
        char_coverage=coverage,
        verdict=verdict,
        fallback_reasons=reasons,
    )


def assess_pages(
    blocks: list[Block],
    *,
    page_width: float = 612.0,
    page_count: int | None = None,
) -> list[PageQuality]:
    """Assess every page that has blocks (plus pages 1..page_count if given)."""
    by_page: dict[int, list[Block]] = {}
    for block in blocks:
        by_page.setdefault(block.page, []).append(block)
    if page_count is not None:
        for page in range(1, page_count + 1):
            by_page.setdefault(page, [])
    return [
        assess_page_quality(page, page_blocks, page_width=page_width)
        for page, page_blocks in sorted(by_page.items())
    ]


def fuse_page_candidates(
    primary_blocks: list[Block],
    alternate_blocks: list[Block],
    flagged_pages: list[int],
    *,
    page_width: float = 612.0,
    primary_engine: str = "pymupdf",
    alternate_engine: str = "pdfplumber",
) -> tuple[list[Block], dict[int, str]]:
    """V4.2 Active Quality Gate：页级候选融合。

    对 LOW/SUSPECT 页比较主/备引擎的页级质量（verdict 优先、次之
    fallback 数量），严格更优才换用备选；备选引擎无该页内容时保留主
    引擎。返回 (融合后的 blocks, {page: 采用的引擎})。
    """

    def _rank(page: int, blocks: list[Block]) -> tuple[int, int]:
        page_blocks = [block for block in blocks if block.page == page]
        if not page_blocks:
            return (9, 0)  # 无内容 → 绝不采用
        quality = assess_page_quality(page, page_blocks, page_width=page_width)
        return ({"GOOD": 0, "SUSPECT": 1, "LOW": 2}[quality.verdict], len(quality.fallback_reasons))

    chosen: dict[int, str] = {}
    merged = [block for block in primary_blocks if block.page not in flagged_pages]
    for page in flagged_pages:
        alternate_better = _rank(page, alternate_blocks) < _rank(page, primary_blocks)
        engine = alternate_engine if alternate_better else primary_engine
        chosen[page] = engine
        source = alternate_blocks if engine == alternate_engine else primary_blocks
        merged.extend(block for block in source if block.page == page)
    merged.sort(key=lambda block: (block.page, block.block_index))
    return merged, chosen
