"""Production adapter for the canonical-first Parser v2 pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass

from paperlens_core.ir.canonical import (
    CanonicalDocument,
    blocks_from_canonical_document,
)
from paperlens_core.parsing import ParsePipeline, PipelineResult, QualityInspector
from paperlens_core.parsing.backends import (
    DoclingBackend,
    GROBIDBackend,
    PaddleOCRVLBackend,
    PDFPlumberBackend,
    PyMuPDFBackend,
)


@dataclass
class ProductionParseResult:
    document: CanonicalDocument
    blocks: list[object]
    page_count: int
    pipeline: PipelineResult
    primary_backend: str


class ProductionParseService:
    """Build and execute the production Parser v2 backend registry."""

    def __init__(self, *, backends: list[object] | None = None) -> None:
        self.backends = backends or self._default_backends()

    @staticmethod
    def _default_backends() -> list[object]:
        # Order is policy: structure first, deterministic local fallbacks next,
        # expensive visual repair last. Unavailable providers self-disable.
        return [
            DoclingBackend(),
            PyMuPDFBackend(),
            PDFPlumberBackend(),
            GROBIDBackend(os.environ.get("PAPERLENS_GROBID_URL", "")),
            PaddleOCRVLBackend(),
        ]

    def parse(
        self,
        *,
        document_path: str,
        raw_bytes: bytes,
        source_version_id: str,
        paper_id: str,
        max_repair_pages: int = 20,
    ) -> ProductionParseResult:
        pipeline = ParsePipeline(
            self.backends,
            quality=QualityInspector(),
        ).run(
            document_path=document_path,
            raw_bytes=raw_bytes,
            source_version_id=source_version_id,
            max_repair_pages=max_repair_pages,
        )
        blocks = blocks_from_canonical_document(pipeline.document, paper_id=paper_id)
        primary = next(iter(pipeline.fusion.chosen_pages.values()), "")
        return ProductionParseResult(
            document=pipeline.document,
            blocks=blocks,
            page_count=max(pipeline.probe.page_count, max((node.page for node in pipeline.document.nodes), default=0)),
            pipeline=pipeline,
            primary_backend=primary,
        )
