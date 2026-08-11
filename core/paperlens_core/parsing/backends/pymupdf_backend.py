"""PyMuPDF backend adapter for Parser v2.

Wraps the existing V1 ``pymupdf_adapter`` and emits ParseCandidates.  The
backend also exposes cheap ``page_stats`` used by DocumentProbe.
"""

from __future__ import annotations

from .base import BaseBackend

NAME = "pymupdf"


class PyMuPDFBackend(BaseBackend):
    """Capabilities: TEXT / LAYOUT / GEOMETRY (+ basic TABLE via find_tables)."""

    name = NAME

    def capabilities(self) -> set:
        from ..contracts import Capability

        return {Capability.TEXT, Capability.LAYOUT, Capability.GEOMETRY}

    def _parse(self, raw_bytes: bytes, document_path: str, page_range=None):
        from ..candidates import CandidateKind, ParseCandidate

        try:
            from ...pymupdf_adapter import (
                parse_pdf_bytes_pymupdf,
            )
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"PyMuPDF unavailable: {exc}") from exc

        parsed = parse_pdf_bytes_pymupdf(raw_bytes, document_path)
        blocks = list(parsed.blocks)
        candidates: list[ParseCandidate] = []
        for block in blocks:
            block_type = str(getattr(block, "block_type", "") or "TEXT")
            if block_type == "TABLE":
                kind = CandidateKind.TABLE
            else:
                kind = CandidateKind.PARAGRAPH
            candidates.append(
                ParseCandidate(
                    candidate_id=f"{NAME}-{len(candidates):05d}",
                    backend=NAME,
                    page=getattr(block, "page", 1) or 1,
                    kind=kind,
                    text=getattr(block, "text", "") or "",
                    bbox=getattr(block, "bbox", None),
                    confidence=0.8,
                    raw_payload={
                        "font_size": getattr(block, "font_size", None),
                        "is_bold": getattr(block, "is_bold", False),
                        "table_cell": (block.metadata or {}).get("table_cell", False),
                        "source_engine": "pymupdf",
                    },
                )
            )
        return candidates

    def page_stats(self) -> dict[int, dict[str, object]]:
        stats: dict[int, dict[str, object]] = {}
        import fitz

        from ...pymupdf_adapter import extract_spans, mark_table_regions

        with fitz.open(self._document_path or "") as document:
            for page_index in range(len(document)):
                page = document[page_index]
                text = page.get_text()
                spans = []
                try:
                    spans = extract_spans(page)
                    table_bboxes = mark_table_regions(page, spans)
                except Exception:  # noqa: BLE001 - stats are best-effort
                    table_bboxes = []
                stats[page_index + 1] = {
                    "text_chars": len(text.strip()),
                    "image_boxes": len(page.get_images(full=True)),
                    "font_sizes": [s.font_size for s in spans],
                    "x0s": [s.bbox[0] for s in spans],
                    "table_lines": len(table_bboxes),
                    "formula_symbols": sum(
                        1 for s in spans if "\\" in s.text or "=" in s.text
                    ),
                }
        return stats
