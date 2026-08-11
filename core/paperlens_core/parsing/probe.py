"""DocumentProbe: cheap pre-parse diagnostics (改进方案1 §三 / 改进方案2 §14).

The probe inspects a PDF *without* doing a full parse: text coverage,
image-only page ratio, column likelihood, font entropy, table/formula
density.  It decides whether the document is born-digital, scanned, mixed,
and which backends/regions the planner should engage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field


class DocumentType(str):
    BORN_DIGITAL = "BORN_DIGITAL"
    SCANNED = "SCANNED"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class ProbeReport(BaseModel):
    """Outcome of DocumentProbe."""

    model_config = ConfigDict(extra="allow")

    document_type: str = DocumentType.UNKNOWN
    layout: str = "UNKNOWN"  # SINGLE_COLUMN / TWO_COLUMN / MULTI_COLUMN / UNKNOWN
    ocr_required: bool = False
    table_complexity: str = "LOW"  # LOW / MEDIUM / HIGH
    formula_density: float = 0.0
    text_coverage: float = 0.0
    image_only_page_ratio: float = 0.0
    scanned_page_ratio: float = 0.0
    page_count: int = 0
    # pages the planner should route to heavy backends (tables, formulas)
    table_heavy_pages: list[int] = Field(default_factory=list)
    formula_heavy_pages: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def to_plan_hints(self) -> dict[str, object]:
        return {
            "document_type": self.document_type,
            "layout": self.layout,
            "ocr_required": self.ocr_required,
            "table_complexity": self.table_complexity,
            "formula_density": self.formula_density,
            "text_coverage": self.text_coverage,
        }


@dataclass
class _ProbeSignals:
    """Raw signals collected by the probe (per page)."""

    page_count: int = 0
    text_chars_per_page: dict[int, int] = field(default_factory=dict)
    image_bbox_pages: dict[int, int] = field(default_factory=dict)
    text_bbox_pages: dict[int, int] = field(default_factory=dict)
    x0_values: list[float] = field(default_factory=list)
    font_sizes: list[float] = field(default_factory=list)
    table_line_pages: dict[int, int] = field(default_factory=dict)
    formula_symbol_pages: dict[int, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Text-heavy analysis shared by backend-agnostic probes.
# ---------------------------------------------------------------------------

_TEXT_SYMBOLS = re.compile(r"[\w\u4e00-\u9fff]+")
_TABLE_MARKERS = re.compile(r"\b(table|tbl|\\hline|\\begin\{tabular\})\b", re.IGNORECASE)
_FORMULA_MARKERS = re.compile(r"(\\frac|\\sum|\\int|\\alpha|\\beta|\\times|\bm=\d+\b|\$\$?)")


def analyze_page_text(text: str, *, x0s: list[float] | None = None) -> dict[str, float]:
    """Cheap heuristics for a single page's text block list.

    Returns dict with ``coverage``, ``table_markers``, ``formula_markers``,
    ``column_hint`` (0=unknown, 1=single, 2=two+).
    """
    total_chars = sum(len(t) for t in text if t)
    coverage = min(1.0, total_chars / 2_200.0)  # ~ 2200 chars is a full page
    table_markers = sum(len(_TABLE_MARKERS.findall(t)) for t in text)
    formula_markers = sum(len(_FORMULA_MARKERS.findall(t)) for t in text)

    column_hint = 0
    if x0s:
        distinct_x0 = round(min(len(set(round(x / 20.0) for x in x0s)), 4))
        column_hint = 1 if distinct_x0 <= 1 else 2 if distinct_x0 == 2 else 3

    return {
        "coverage": round(coverage, 4),
        "table_markers": float(table_markers),
        "formula_markers": float(formula_markers),
        "column_hint": float(column_hint),
    }


class DocumentProbe:
    """Probe a PDF via a list of backends; aggregate into a ProbeReport."""

    def __init__(self, backends: list[object]):
        self.backends = backends

    def probe(self, document_path: str, raw_bytes: bytes | None = None) -> ProbeReport:
        signals = _ProbeSignals()
        # Prefer a backend that can at least report page geometry cheaply.
        for backend in self.backends:
            try:
                # Make the document path available to backends whose page_stats
                # needs to reopen the file (PyMuPDFBackend etc.).
                if hasattr(backend, "_document_path"):
                    backend._document_path = document_path
                probe = backend.probe(document_path, raw_bytes)
                if probe.available:
                    self._collect(backend, probe, signals)
            except Exception:  # noqa: BLE001 - probing is best-effort
                continue
        return self._build_report(signals)

    def _collect(self, backend: object, probe: object, signals: _ProbeSignals) -> None:
        capabilities = getattr(probe, "capabilities", set())
        if not capabilities:
            return
        # Only geometry-capable backends contribute real page data.
        from .contracts import Capability

        if Capability.GEOMETRY not in capabilities and Capability.LAYOUT not in capabilities:
            return
        # Ask the backend for cheap page-level stats via an optional hook.
        stats = getattr(backend, "page_stats", None)
        if stats:
            try:
                per_page = stats()
                for page, stat in per_page.items():
                    signals.page_count = max(signals.page_count, page)
                    signals.text_chars_per_page[page] = max(
                        signals.text_chars_per_page.get(page, 0), stat.get("text_chars", 0)
                    )
                    signals.image_bbox_pages[page] = max(
                        signals.image_bbox_pages.get(page, 0), stat.get("image_boxes", 0)
                    )
                    signals.font_sizes.extend(stat.get("font_sizes", []))
                    signals.x0_values.extend(stat.get("x0s", []))
                    signals.table_line_pages[page] = max(
                        signals.table_line_pages.get(page, 0), stat.get("table_lines", 0)
                    )
                    signals.formula_symbol_pages[page] = max(
                        signals.formula_symbol_pages.get(page, 0), stat.get("formula_symbols", 0)
                    )
            except Exception:  # noqa: BLE001 - best effort
                pass

    def _build_report(self, signals: _ProbeSignals) -> ProbeReport:
        page_count = max(1, signals.page_count)
        text_chars = sum(signals.text_chars_per_page.values())
        coverage = min(1.0, text_chars / max(1, page_count) / 2_200.0)

        image_pages = sum(1 for c in signals.image_bbox_pages.values() if c > 0)
        image_only_ratio = image_pages / page_count

        # scanned = most pages have essentially no text but have images
        scanned_pages = sum(
            1
            for page in range(1, page_count + 1)
            if signals.text_chars_per_page.get(page, 0) < 80
            and signals.image_bbox_pages.get(page, 0) > 0
        )
        scanned_ratio = scanned_pages / page_count

        if scanned_ratio > 0.6:
            doc_type = DocumentType.SCANNED
        elif scanned_ratio > 0.15:
            doc_type = DocumentType.MIXED
        elif coverage > 0.4:
            doc_type = DocumentType.BORN_DIGITAL
        else:
            doc_type = DocumentType.UNKNOWN

        x0s = signals.x0_values
        column_hint = 0
        if x0s:
            distinct = round(min(len(set(round(x / 20.0) for x in x0s)), 4))
            column_hint = 1 if distinct <= 1 else 2 if distinct == 2 else 3
        layout = (
            "SINGLE_COLUMN"
            if column_hint == 1
            else "TWO_COLUMN"
            if column_hint == 2
            else "MULTI_COLUMN"
            if column_hint >= 3
            else "UNKNOWN"
        )

        table_pages = sorted(
            page
            for page, count in signals.table_line_pages.items()
            if count >= 3
        )
        formula_pages = sorted(
            page
            for page, count in signals.formula_symbol_pages.items()
            if count >= 2
        )
        table_complexity = (
            "HIGH" if len(table_pages) >= 6 else "MEDIUM" if table_pages else "LOW"
        )

        notes: list[str] = []
        if doc_type == DocumentType.SCANNED:
            notes.append("SCANNED: 大部分页面无可抽取文本，需要 OCR 后端")
        if doc_type == DocumentType.MIXED:
            notes.append("MIXED: 混合文本页与扫描页")
        if layout == "TWO_COLUMN":
            notes.append("TWO_COLUMN: 双栏布局，段落重建与阅读顺序需注意")
        if table_complexity == "HIGH":
            notes.append("TABLE_HIGH: 表格密集，建议表格专用后端")

        return ProbeReport(
            document_type=doc_type,
            layout=layout,
            ocr_required=doc_type in (DocumentType.SCANNED, DocumentType.MIXED),
            table_complexity=table_complexity,
            formula_density=round(len(formula_pages) / max(1, page_count), 3),
            text_coverage=round(coverage, 3),
            image_only_page_ratio=round(image_only_ratio, 3),
            scanned_page_ratio=round(scanned_ratio, 3),
            page_count=page_count,
            table_heavy_pages=table_pages,
            formula_heavy_pages=formula_pages,
            notes=notes,
        )
