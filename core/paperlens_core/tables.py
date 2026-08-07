"""Table structure helpers shared by the HTML and PDF paths (V3.12).

改进方案2.md §10.3: every table asset carries a structured cell matrix and a
CSV export so the UI can render a real table and offer one-click download.
rowspan cells are carried into later rows (their text is repeated) so the
CSV is rectangular and lossless enough for analysis tools.
"""

from __future__ import annotations

import csv
import io
from typing import Any


def expand_cells_to_grid(raw_rows: list[list[dict[str, Any]]]) -> list[list[str]]:
    """Expand a cell list (text/rowspan/colspan) into a rectangular grid.

    Column order is preserved; a rowspan cell occupies its column in the
    following rows (repeated text); colspan cells keep a single column (the
    span is a rendering concern the CSV cannot represent).
    """
    grid: list[list[str]] = []
    pending: dict[int, tuple[int, str]] = {}  # col -> (rows_left, text)

    for row in raw_rows:
        row_cells: dict[int, str] = {}
        # continue rowspan cells from previous rows (their columns are taken)
        for col_index in sorted(pending):
            remaining, text = pending[col_index]
            row_cells[col_index] = text
            if remaining <= 1:
                del pending[col_index]
            else:
                pending[col_index] = (remaining - 1, text)
        # place this row's cells into the first free columns
        col = 0
        for cell in row:
            while col in row_cells:
                col += 1
            text = (cell.get("text") or "").strip()
            row_cells[col] = text
            rowspan = int(cell.get("rowspan", 1) or 1)
            if rowspan > 1:
                pending[col] = (rowspan - 1, text)
            col += 1
        if not row_cells:
            continue
        grid.append(
            [row_cells.get(index, "") for index in range(max(row_cells) + 1)]
        )
    return grid


def rows_to_csv(grid: list[list[str]]) -> str:
    """Rectangular grid -> CSV text (utf-8, csv module quoting)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in grid:
        writer.writerow([(cell or "").replace("\n", " ") for cell in row])
    return buffer.getvalue()


def grid_to_html(grid: list[list[str]]) -> str:
    """Grid -> minimal <table> markup for inline rendering (V3.12)."""
    if not grid:
        return ""
    lines = ["<table>"]
    for row_index, row in enumerate(grid):
        tag = "th" if row_index == 0 else "td"
        lines.append(
            "<tr>" + "".join(f"<{tag}>{cell}</{tag}>" for cell in row) + "</tr>"
        )
    lines.append("</table>")
    return "".join(lines)
