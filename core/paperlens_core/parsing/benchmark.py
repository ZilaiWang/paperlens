"""Parser v2 Benchmark (改进方案2 Phase C).

Runs the ParsePipeline over a corpus of PDFs and aggregates per-backend
quality signals (coverage, tiny-node ratio, table/formula recovery, verdict
mix).  This is the objective basis for deciding whether to add a backend
(GROBID/MinerU/OCR) or tune the canonicalizer.

Output shape is stable JSON, so the benchmark can be wired into CI.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .pipeline import ParsePipeline


class BenchmarkDocument(BaseModel):
    model_config = ConfigDict(extra="allow")

    path: str
    label: str = ""
    expected_page_count: int = 0


class BenchmarkEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    label: str
    document_type: str = ""
    page_count: int = 0
    node_count: int = 0
    verdict: str = ""
    coverage_ratio: float = 0.0
    tiny_node_ratio: float = 0.0
    table_node_count: int = 0
    formula_node_count: int = 0
    issues: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    repair_passes: int = 0
    object_quality: dict[str, float] = Field(default_factory=dict)
    backend_errors: dict[str, str] = Field(default_factory=dict)


class BenchmarkReport(BaseModel):
    model_config = ConfigDict(extra="allow")

    backends: list[str] = Field(default_factory=list)
    documents: list[BenchmarkEntry] = Field(default_factory=list)
    aggregate: dict[str, float] = Field(default_factory=dict)


def run_benchmark(
    documents: list[BenchmarkDocument],
    pipeline: ParsePipeline,
) -> BenchmarkReport:
    entries: list[BenchmarkEntry] = []
    for document in documents:
        started = time.monotonic()
        raw = Path(document.path).read_bytes()
        result = pipeline.run(
            document_path=document.path,
            raw_bytes=raw,
            source_version_id=f"bench-{document.label or document.path}",
        )
        duration = int((time.monotonic() - started) * 1000)
        entries.append(
            BenchmarkEntry(
                label=document.label or Path(document.path).name,
                document_type=result.probe.document_type,
                page_count=result.probe.page_count,
                node_count=result.quality.node_count,
                verdict=result.quality.verdict,
                coverage_ratio=result.quality.coverage_ratio,
                tiny_node_ratio=result.quality.tiny_node_ratio,
                table_node_count=result.quality.table_node_count,
                formula_node_count=result.quality.formula_node_count,
                issues=result.quality.issues,
                duration_ms=duration,
                repair_passes=result.repair_passes,
                object_quality=result.quality.object_quality,
                backend_errors=result.backend_errors,
            )
        )

    if entries:
        good = sum(1 for e in entries if e.verdict == "GOOD")
        aggregate = {
            "good_ratio": round(good / len(entries), 3),
            "avg_coverage": round(
                sum(e.coverage_ratio for e in entries) / len(entries), 3
            ),
            "avg_tiny_ratio": round(
                sum(e.tiny_node_ratio for e in entries) / len(entries), 3
            ),
            "total_documents": float(len(entries)),
        }
    else:
        aggregate = {}

    backends = [
        getattr(b, "name", type(b).__name__) for b in pipeline.backends
    ]
    return BenchmarkReport(backends=backends, documents=entries, aggregate=aggregate)


def run_benchmark_json(
    documents: list[BenchmarkDocument],
    pipeline: ParsePipeline,
) -> str:
    report = run_benchmark(documents, pipeline)
    return json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
