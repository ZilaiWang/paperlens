"""pdfplumber backend adapter for Parser v2.

Wraps the existing V1 ``parser`` (pdfplumber path) and emits ParseCandidates.
"""

from __future__ import annotations

from .base import BaseBackend

NAME = "pdfplumber"


class PDFPlumberBackend(BaseBackend):
    """Capabilities: TEXT / LAYOUT / GEOMETRY."""

    name = NAME

    def capabilities(self) -> set:
        from ..contracts import Capability

        return {Capability.TEXT, Capability.LAYOUT, Capability.GEOMETRY}

    def _parse(self, raw_bytes: bytes, document_path: str, page_range=None):
        from ..candidates import CandidateKind, ParseCandidate

        try:
            from ...parser import parse_pdf_bytes
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"pdfplumber unavailable: {exc}") from exc

        parsed = parse_pdf_bytes(raw_bytes, document_path)
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
                    confidence=0.75,
                    raw_payload={"source_engine": "pdfplumber"},
                )
            )
        return candidates

    def page_stats(self) -> dict[int, dict[str, object]]:
        """No cheap geometric stats exposed by pdfplumber here; rely on probe."""
        return {}
