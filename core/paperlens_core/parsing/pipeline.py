"""Parser v2 pipeline: probe → plan → parse → canonize → fuse → quality → repair.

This is the successor of the V1 ``ParseRouter`` (改进方案1 §三).  The pipeline
orchestrates DocumentProbe, ParsePlanner, ParserBackends, Canonicalizer,
RegionFusion, QualityInspector and RepairPlanner, and emits a
``CanonicalDocument`` plus a ``ParseRun`` audit record.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ..ir.canonical import CanonicalDocument
from .candidates import ParseCandidate
from .canonicalizer import Canonicalizer
from .contracts import ParseRequest
from .fusion import FusionOutcome, RegionFusion
from .planner import ParsePlanner
from .probe import DocumentProbe, ProbeReport
from .quality import ParseQualityReport, QualityInspector
from .repair import RepairPlan, RepairPlanner


@dataclass
class PipelineResult:
    document: CanonicalDocument
    probe: ProbeReport
    quality: ParseQualityReport
    repair_plan: RepairPlan
    parse_run_id: str
    fusion: FusionOutcome = field(default_factory=FusionOutcome)


class ParsePipeline:
    """Orchestrate the full Parser v2 flow for one document."""

    def __init__(
        self,
        backends: list[object],
        *,
        canonicalizer: Canonicalizer | None = None,
        fusion: RegionFusion | None = None,
        quality: QualityInspector | None = None,
        repair: RepairPlanner | None = None,
    ):
        self.backends = backends
        self.canonicalizer = canonicalizer or Canonicalizer()
        self.fusion = fusion or RegionFusion()
        self.quality = quality or QualityInspector()
        names = [getattr(b, "name", type(b).__name__) for b in backends]
        self.repair = repair or RepairPlanner(names)
        self.probe = DocumentProbe(backends)
        self.planner = ParsePlanner(backends)

    def run(
        self,
        *,
        document_path: str,
        raw_bytes: bytes | None = None,
        source_version_id: str,
        max_repair_pages: int = 20,
    ) -> PipelineResult:
        parse_run_id = f"pr-{uuid.uuid4().hex[:12]}"

        probe = self.probe.probe(document_path, raw_bytes)
        plan = self.planner.plan(probe)

        # Execute plan steps; collect candidates per backend.
        candidates_by_backend: dict[str, list[ParseCandidate]] = {}
        for step in plan.steps:
            backend = next(
                (b for b in self.backends if getattr(b, "name", "") == step.backend),
                None,
            )
            if backend is None:
                continue
            request = ParseRequest(
                document_path=document_path,
                raw_bytes=raw_bytes,
                region=step.region,
                page_range=step.page_range,
                hints=probe.to_plan_hints(),
            )
            result = backend.parse(request)
            if result.error:
                for fallback_name in step.fallbacks:
                    fallback = next(
                        (b for b in self.backends if getattr(b, "name", "") == fallback_name),
                        None,
                    )
                    if fallback is None:
                        continue
                    fallback_result = fallback.parse(request)
                    if not fallback_result.error:
                        result = fallback_result
                        break
            for candidate in result.candidates:
                candidates_by_backend.setdefault(result.backend, []).append(candidate)

        fusion = self.fusion.fuse(
            candidates_by_backend,
            canonicalizer=self.canonicalizer,
            source_version_id=source_version_id,
            parse_run_id=parse_run_id,
        )

        document = CanonicalDocument(
            document_id=source_version_id,
            source_version_id=source_version_id,
            parse_run_ids=[parse_run_id],
            nodes=fusion.nodes,
        )

        quality = self.quality.inspect(document)
        repair_plan = self.repair.plan(
            quality,
            primary_backend=next(iter(fusion.chosen_pages.values()), ""),
            max_pages=max_repair_pages,
        )

        return PipelineResult(
            document=document,
            probe=probe,
            quality=quality,
            repair_plan=repair_plan,
            parse_run_id=parse_run_id,
            fusion=fusion,
        )
