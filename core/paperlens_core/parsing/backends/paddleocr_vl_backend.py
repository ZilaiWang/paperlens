"""Selective visual repair through the optional PaddleOCR-VL pipeline."""

from __future__ import annotations

import importlib.util
from typing import Any, Callable

from .base import BaseBackend


class PaddleOCRVLBackend(BaseBackend):
    name = "paddleocr-vl"

    def __init__(self, *, pipeline_factory: Callable[[], object] | None = None) -> None:
        super().__init__()
        self.pipeline_factory = pipeline_factory
        self._pipeline: object | None = None

    def available(self) -> bool:
        return self.pipeline_factory is not None or importlib.util.find_spec("paddleocr") is not None

    def capabilities(self) -> set:
        from ..contracts import Capability

        return {
            Capability.OCR,
            Capability.TEXT,
            Capability.LAYOUT,
            Capability.TABLE,
            Capability.FORMULA,
            Capability.FIGURE,
        }

    def _parse(self, raw_bytes: bytes, document_path: str, page_range=None):
        if self._pipeline is None:
            if self.pipeline_factory is not None:
                self._pipeline = self.pipeline_factory()
            else:
                from paddleocr import PaddleOCRVL

                self._pipeline = PaddleOCRVL()
        results = list(self._pipeline.predict(input=document_path))  # type: ignore[attr-defined]
        return _visual_candidates(results, page_range=page_range)


def _visual_candidates(results: list[Any], *, page_range=None):
    from ..candidates import CandidateKind, ParseCandidate

    candidates: list[ParseCandidate] = []
    for result_index, result in enumerate(results, start=1):
        page = int(getattr(result, "page_index", result_index - 1) or 0) + 1
        if page_range and not (page_range[0] <= page <= page_range[1]):
            continue
        payload = getattr(result, "json", None)
        payload = payload() if callable(payload) else payload
        if not isinstance(payload, dict):
            payload = getattr(result, "res", {}) or {}
        elements = payload.get("parsing_res_list") or payload.get("layout_parsing_result") or []
        if isinstance(elements, dict):
            elements = elements.get("parsing_res_list", [])
        for element in elements if isinstance(elements, list) else []:
            if not isinstance(element, dict):
                continue
            text = str(element.get("block_content") or element.get("text") or "").strip()
            label = str(element.get("block_label") or element.get("label") or "text").lower()
            bbox_raw = element.get("block_bbox") or element.get("bbox")
            bbox = tuple(float(value) for value in bbox_raw[:4]) if isinstance(bbox_raw, list) and len(bbox_raw) >= 4 else None
            kind = CandidateKind.PARAGRAPH
            if "table" in label:
                kind = CandidateKind.TABLE
            elif any(token in label for token in ("formula", "equation")):
                kind = CandidateKind.FORMULA
            elif any(token in label for token in ("figure", "image", "chart")):
                kind = CandidateKind.FIGURE
            elif any(token in label for token in ("title", "heading")):
                kind = CandidateKind.HEADING
            if text or kind == CandidateKind.FIGURE:
                candidates.append(
                    ParseCandidate(
                        candidate_id=f"paddleocr-vl-{len(candidates):06d}",
                        backend="paddleocr-vl",
                        page=page,
                        kind=kind,
                        text=text,
                        bbox=bbox,
                        confidence=float(element.get("score") or 0.92),
                        raw_payload={"source_engine": "paddleocr-vl", "visual_repair": True},
                    )
                )
    return candidates
