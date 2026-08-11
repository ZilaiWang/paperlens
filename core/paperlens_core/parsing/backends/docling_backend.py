"""Optional Docling structure backend.

Docling is intentionally not a default dependency.  When installed, this
adapter uses its native document tree as the preferred structure source; when
it is absent, ``probe`` reports the backend unavailable and the lightweight
PyMuPDF/pdfplumber path remains fully usable.
"""

from __future__ import annotations

import importlib.util
from typing import Any

from .base import BaseBackend


class DoclingBackend(BaseBackend):
    name = "docling"

    def available(self) -> bool:
        return importlib.util.find_spec("docling") is not None

    def capabilities(self) -> set:
        from ..contracts import Capability

        return {
            Capability.TEXT,
            Capability.LAYOUT,
            Capability.TABLE,
            Capability.FIGURE,
            Capability.FORMULA,
            Capability.ACADEMIC_STRUCTURE,
            Capability.SEMANTIC,
        }

    def _parse(self, raw_bytes: bytes, document_path: str, page_range=None):
        from docling.document_converter import DocumentConverter

        kwargs = {"raises_on_error": True}
        if page_range is not None:
            kwargs["page_range"] = page_range
        result = DocumentConverter().convert(document_path, **kwargs)
        return self._candidates_from_document(result.document, page_range=page_range)

    def _candidates_from_document(self, document: Any, *, page_range=None):
        from ..candidates import CandidateKind, ParseCandidate

        candidates: list[ParseCandidate] = []
        iterator = getattr(document, "iterate_items", None)
        if not callable(iterator):
            return candidates

        for item_index, value in enumerate(iterator()):
            item = value[0] if isinstance(value, tuple) else value
            text = str(getattr(item, "text", "") or "").strip()
            label = str(getattr(item, "label", "") or type(item).__name__).lower()
            if not text and not any(token in label for token in ("figure", "picture", "table")):
                continue
            page, bbox = _docling_location(item)
            if page_range and not (page_range[0] <= page <= page_range[1]):
                continue
            kind = CandidateKind.PARAGRAPH
            if any(token in label for token in ("title", "section_header", "heading")):
                kind = CandidateKind.HEADING
            elif "table" in label:
                kind = CandidateKind.TABLE
            elif any(token in label for token in ("figure", "picture")):
                kind = CandidateKind.FIGURE
            elif "caption" in label:
                kind = CandidateKind.CAPTION
            elif any(token in label for token in ("formula", "equation")):
                kind = CandidateKind.FORMULA
            elif any(token in label for token in ("reference", "bibliography")):
                kind = CandidateKind.REFERENCE
            candidates.append(
                ParseCandidate(
                    candidate_id=f"docling-{item_index:06d}",
                    backend=self.name,
                    page=page,
                    kind=kind,
                    text=text,
                    bbox=bbox,
                    confidence=0.9,
                    raw_payload={"source_engine": self.name, "docling_label": label},
                )
            )
        return candidates


def _docling_location(item: Any) -> tuple[int, tuple[float, float, float, float] | None]:
    provenance = list(getattr(item, "prov", None) or [])
    if not provenance:
        return 1, None
    prov = provenance[0]
    page = int(getattr(prov, "page_no", 1) or 1)
    box = getattr(prov, "bbox", None)
    if box is None:
        return page, None
    values = [getattr(box, key, None) for key in ("l", "t", "r", "b")]
    if any(value is None for value in values):
        values = [getattr(box, key, None) for key in ("x0", "y0", "x1", "y1")]
    if any(value is None for value in values):
        return page, None
    return page, tuple(float(value) for value in values)  # type: ignore[return-value]
