"""PDF table grid extraction from vector drawings (V3.12).

改进方案2.md §10.3 (wired tables): PyMuPDF exposes the page's vector drawing
paths, so bordered tables are reconstructed as a grid:

    horizontal + vertical lines -> merged boundaries -> cells
    -> text spans assigned to cells by their anchor points

This is deterministic geometry code (题目要求: 确定性逻辑自行编码), with no
ML model involved. Borderless tables stay at the region level (caption +
crop); Docling/PP-StructureV3 remain an optional future backend.
"""

from __future__ import annotations

import re
from typing import Any

LINE_TOLERANCE = 3.0  # pt: lines closer than this merge into one boundary
MIN_H_LINE_LENGTH = 30.0  # pt: horizontal table rules are long
MIN_V_LINE_LENGTH = 5.0  # pt: column separators are often short segments
                         # (12pt per row in many PDFs — fix 2026-08-04)
SPAN_ANCHOR = 0.45  # span center ratio inside the cell box

_FLOAT_RE = re.compile(r"[-+]?\d*\.?\d+")


def _close(a: float, b: float, tolerance: float = LINE_TOLERANCE) -> bool:
    return abs(a - b) <= tolerance


def _merge(values: list[float], tolerance: float = LINE_TOLERANCE) -> list[float]:
    """Sort and merge near-equal coordinates into distinct boundaries."""
    ordered = sorted(values)
    merged: list[float] = []
    for value in ordered:
        if merged and _close(value, merged[-1], tolerance):
            merged[-1] = (merged[-1] + value) / 2
        else:
            merged.append(value)
    return merged


def extract_grid_lines(page: Any) -> tuple[list[float], list[float]]:
    """Horizontal/vertical boundary coordinates from the page's vector paths."""
    horizontal: list[float] = []
    vertical: list[float] = []
    try:
        drawings = page.get_drawings()
    except Exception:  # noqa: BLE001 - missing drawings are not fatal
        return [], []
    for drawing in drawings:
        for item in drawing.get("items", []):
            kind = item[0]
            if kind == "l":  # straight line
                _, p1, p2 = item
                x1, y1 = p1
                x2, y2 = p2
            elif kind == "re":  # rectangle outline (two opposite corners)
                _, rect, *_ = item  # PyMuPDF 1.28: ("re", Rect, extra)
                x1, y1, x2, y2 = rect.x0, rect.y0, rect.x1, rect.y1
            else:
                continue
            length_x = abs(x2 - x1)
            length_y = abs(y2 - y1)
            if length_x > MIN_H_LINE_LENGTH and length_y <= LINE_TOLERANCE:
                horizontal.append((y1 + y2) / 2)
            elif length_y > MIN_V_LINE_LENGTH and length_x <= LINE_TOLERANCE:
                vertical.append((x1 + x2) / 2)
    return _merge(horizontal), _merge(vertical)


def _drop_empty_columns(grid: list[list[str]]) -> list[list[str]]:
    """Remove columns where every cell is empty (noise verticals)."""
    if not grid:
        return grid
    keep = [c for c in range(len(grid[0])) if any(row[c].strip() for row in grid)]
    if not keep:
        return grid
    return [[row[c] for c in keep] for row in grid]


def build_table_grid(
    page: Any,
    *,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> list[list[str]]:
    """Reconstruct a bordered table region as a text grid.

    ``x0..y1`` is the table region (e.g. from pdfplumber's find_tables);
    lines inside it define the grid; text spans fall into cells by their
    anchor (45% into the span's own box).
    """
    page_h, page_v = extract_grid_lines(page)
    xs = [value for value in page_v if x0 - 5 <= value <= x1 + 5]
    ys = [value for value in page_h if y0 - 5 <= value <= y1 + 5]
    if len(xs) < 2 or len(ys) < 2:
        return []
    if len(xs) < 3 or len(ys) < 3:
        return []  # no inner grid: borderless table, skip structured output
    # page text spans
    spans: list[tuple[float, float, str]] = []
    try:
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = (span.get("text") or "").strip()
                    if not text:
                        continue
                    bbox = span.get("bbox")
                    if not bbox:
                        continue
                    center_x = bbox[0] + (bbox[2] - bbox[0]) * SPAN_ANCHOR
                    center_y = bbox[1] + (bbox[3] - bbox[1]) * SPAN_ANCHOR
                    spans.append((center_x, center_y, text))
    except Exception:  # noqa: BLE001 - text layer issues are not fatal
        return []

    rows: list[list[str]] = []
    for row_index in range(len(ys) - 1):
        top, bottom = ys[row_index], ys[row_index + 1]
        cells: list[str] = []
        for col_index in range(len(xs) - 1):
            left, right = xs[col_index], xs[col_index + 1]
            inside = [
                (cy, cx, text)
                for cx, cy, text in spans
                if left - 1 <= cx <= right + 1 and top - 1 <= cy <= bottom + 1
            ]
            # spans read in visual order (top-to-bottom, left-to-right)
            inside.sort()
            cells.append(" ".join(text for _, _, text in inside))
        rows.append(cells)
    return _drop_empty_columns(rows)
