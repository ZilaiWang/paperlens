"""LaTeX template fingerprints: layout priors that make parsing deterministic.

CV/ML papers overwhelmingly come from a small set of standard templates
(CVPR/ICCV/ECCV/NeurIPS/ICML/PMLR/AAAI/arXiv). Their layout parameters
(column bounds, body font size, line gap, indent, caption prefix, reference
style) are fully predictable. A fingerprint lets the paragraph rebuild and
column detection use known values instead of heuristics, and falls back to
heuristics for unknown templates.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .models import Block, BlockType

REGISTRY_PATH = Path(__file__).resolve().parent / "template_registry.json"


@dataclass(slots=True)
class TemplateFingerprint:
    name: str
    page_width: float = 612.0
    page_height: float = 792.0
    column_count: int = 1  # 1 or 2
    left_col_x1: float | None = None  # two-column: left column right edge
    right_col_x0: float | None = None  # two-column: right column left edge
    body_font_size: float = 10.0
    line_height: float = 12.0
    heading_font_size: float = 12.0
    indent: float = 12.0
    caption_prefix: str = ""  # e.g. "Fig. 1:" or "Figure 1:"
    references_style: str = "unknown"  # numeric | author_year | unknown

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "page_width": self.page_width,
            "page_height": self.page_height,
            "column_count": self.column_count,
            "left_col_x1": self.left_col_x1,
            "right_col_x0": self.right_col_x0,
            "body_font_size": self.body_font_size,
            "line_height": self.line_height,
            "heading_font_size": self.heading_font_size,
            "indent": self.indent,
            "caption_prefix": self.caption_prefix,
            "references_style": self.references_style,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "TemplateFingerprint":
        return cls(**{key: payload[key] for key in cls.__slots__ if key in payload})


def _mode(values: list[float]) -> float:
    return Counter(round(value, 1) for value in values).most_common(1)[0][0]


def detect_columns(blocks: list[Block], page_width: float) -> tuple[int, float | None, float | None]:
    """Two-column detection: largest x0 gap among line-width fragments."""
    fragments = [
        (block.bbox[0], block.bbox[2])
        for block in blocks
        if block.block_type == BlockType.TEXT
        and block.bbox[2] - block.bbox[0] <= page_width * 0.55
        and block.bbox[2] - block.bbox[0] >= 50.0
    ]
    if len(fragments) < 8:
        return 1, None, None
    starts = sorted(x0 for x0, _ in fragments)
    gaps = [(starts[index + 1] - starts[index], index) for index in range(len(starts) - 1)]
    best_gap, split_index = max(gaps, key=lambda item: item[0])
    if best_gap <= max(page_width * 0.05, 30.0):
        return 1, None, None
    threshold = (starts[split_index] + starts[split_index + 1]) / 2
    left_x1 = _mode([x1 for x0, x1 in fragments if x0 < threshold])
    right_x0 = _mode([x0 for x0, _ in fragments if x0 >= threshold])
    if right_x0 - left_x1 <= max(page_width * 0.02, 10.0):
        return 1, None, None
    return 2, left_x1, right_x0


def _references_style(blocks: list[Block]) -> str:
    ref_texts = [
        block.text
        for block in blocks
        if block.block_type == BlockType.TEXT
        and re.search(r"(?:19|20)\d{2}", block.text)
        and len(block.text) > 60
    ]
    if not ref_texts:
        return "unknown"
    numeric = sum(1 for text in ref_texts if text.strip().startswith("["))
    author_year = sum(1 for text in ref_texts if re.match(r"^[A-Z][A-Za-z-]+,", text.strip()))
    if numeric > author_year:
        return "numeric"
    if author_year > 0:
        return "author_year"
    return "unknown"


def extract_fingerprint(blocks: list[Block], *, page_width: float, page_height: float) -> TemplateFingerprint:
    """Measure layout parameters from a parsed paper (best-effort, human-checked)."""
    text_blocks = [block for block in blocks if block.block_type == BlockType.TEXT]
    sizes = [block.font_size for block in text_blocks if block.font_size]
    body_font = _mode(sizes) if sizes else 10.0
    heights = [block.bbox[3] - block.bbox[1] for block in text_blocks]
    line_height = _mode(heights) if heights else body_font * 1.2
    headings = [
        block.font_size
        for block in text_blocks
        if block.font_size and block.font_size >= body_font * 1.15 and len(block.text.split()) <= 8
    ]
    heading_font = _mode(headings) if headings else body_font * 1.2
    # per-page column detection, majority vote (page layouts may differ)
    pages: dict[int, list[Block]] = {}
    for block in text_blocks:
        pages.setdefault(block.page, []).append(block)
    # text-heavy pages only: figure/table pages dilute the column signal
    votes: list[tuple[int, float | None, float | None]] = [
        detect_columns(page_blocks, page_width)
        for page_blocks in pages.values()
        if len(page_blocks) >= 20
    ]
    if not votes:
        votes = [detect_columns(page_blocks, page_width) for page_blocks in pages.values()]
    column_count = Counter(count for count, _, _ in votes).most_common(1)[0][0]
    two_column_votes = [(lx1, rx0) for count, lx1, rx0 in votes if count == 2 and lx1 and rx0]
    if two_column_votes:
        left_x1 = _mode([lx1 for lx1, _ in two_column_votes])
        right_x0 = _mode([rx0 for _, rx0 in two_column_votes])
    else:
        left_x1, right_x0 = None, None
    # indent: first-line indentation relative to the left column start
    column_start = min(block.bbox[0] for block in text_blocks if block.bbox[2] - block.bbox[0] > 100)
    indent_candidates = [
        block.bbox[0] - column_start
        for block in text_blocks
        if block.bbox[0] - column_start > 5 and block.bbox[0] - column_start < body_font * 3
    ]
    indent = _mode(indent_candidates) if indent_candidates else 12.0
    caption_prefix = ""
    for block in text_blocks:
        text = block.text.strip()
        if re.match(r"^(Figure|Fig\.?)\s+\w+", text):
            caption_prefix = re.match(r"^(Figure|Fig\.?)\s+\w+", text).group(0)
            break
    return TemplateFingerprint(
        name="measured",
        page_width=page_width,
        page_height=page_height,
        column_count=column_count,
        left_col_x1=left_x1,
        right_col_x0=right_x0,
        body_font_size=body_font,
        line_height=line_height,
        heading_font_size=heading_font,
        indent=indent,
        caption_prefix=caption_prefix,
        references_style=_references_style(blocks),
    )


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, TemplateFingerprint]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {name: TemplateFingerprint.from_json(data) for name, data in payload.items()}


def save_registry(registry: dict[str, TemplateFingerprint], path: Path = REGISTRY_PATH) -> None:
    payload = {name: fingerprint.to_json() for name, fingerprint in registry.items()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def match_template(fingerprint: TemplateFingerprint, registry: dict[str, TemplateFingerprint]) -> TemplateFingerprint | None:
    """Best-effort match: same column count and close page size/body font."""
    best: TemplateFingerprint | None = None
    best_score = 0.0
    for candidate in registry.values():
        if candidate.column_count != fingerprint.column_count:
            continue
        score = 0.0
        if abs(candidate.page_width - fingerprint.page_width) < 6:
            score += 1.0
        if abs(candidate.body_font_size - fingerprint.body_font_size) < 0.5:
            score += 1.0
        if abs(candidate.line_height - fingerprint.line_height) < 1.5:
            score += 0.5
        if candidate.left_col_x1 and fingerprint.left_col_x1:
            if abs(candidate.left_col_x1 - fingerprint.left_col_x1) < 8:
                score += 1.5
        if candidate.right_col_x0 and fingerprint.right_col_x0:
            if abs(candidate.right_col_x0 - fingerprint.right_col_x0) < 8:
                score += 1.5
        if score > best_score:
            best_score = score
            best = candidate
    return best if best_score >= 2.5 else None
