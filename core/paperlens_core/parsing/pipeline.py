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
    initial_quality: ParseQualityReport | None = None
    repair_passes: int = 0
    backend_errors: dict[str, str] = field(default_factory=dict)


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
        self._uses_default_repair = repair is None
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
        if getattr(self.quality, "page_count", None) is None and probe.page_count:
            self.quality.page_count = probe.page_count
        repair_planner = (
            RepairPlanner(probe.available_backends)
            if self._uses_default_repair
            else self.repair
        )

        # Execute plan steps; collect candidates per backend.
        candidates_by_backend: dict[str, list[ParseCandidate]] = {}
        backend_errors: dict[str, str] = {}
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
                backend_errors[result.backend] = result.error
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
                    backend_errors[fallback_result.backend] = fallback_result.error
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

        initial_quality = self.quality.inspect(document)
        repair_plan = repair_planner.plan(
            initial_quality,
            primary_backend=next(iter(fusion.chosen_pages.values()), ""),
            max_pages=max_repair_pages,
        )

        repair_passes = 0
        attempted_pages: set[tuple[int, str]] = set()
        quality = initial_quality
        current_plan = repair_plan
        for pass_index in range(2):
            changed = False
            for target in current_plan.targets:
                key = (target.page, target.alternative_backend)
                if key in attempted_pages:
                    continue
                attempted_pages.add(key)
                target.attempted = True
                backend = next(
                    (b for b in self.backends if getattr(b, "name", "") == target.alternative_backend),
                    None,
                )
                if backend is None:
                    continue
                repair_result = backend.parse(
                    ParseRequest(
                        document_path=document_path,
                        raw_bytes=raw_bytes,
                        page_range=(target.page, target.page),
                        hints={**probe.to_plan_hints(), "repair_pass": pass_index + 1},
                    )
                )
                if repair_result.error:
                    backend_errors[repair_result.backend] = repair_result.error
                    continue
                if repair_result.candidates:
                    candidates_by_backend.setdefault(repair_result.backend, []).extend(
                        repair_result.candidates
                    )
                    target.repaired = True
                    changed = True
            if not changed:
                break
            repair_passes += 1
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
            if quality.verdict == "GOOD":
                break
            current_plan = repair_planner.plan(
                quality,
                primary_backend=next(iter(fusion.chosen_pages.values()), ""),
                max_pages=max(0, max_repair_pages - len(attempted_pages)),
            )
            repair_plan.targets.extend(current_plan.targets)
        repair_plan.passes = repair_passes

        return PipelineResult(
            document=document,
            probe=probe,
            quality=quality,
            repair_plan=repair_plan,
            parse_run_id=parse_run_id,
            fusion=fusion,
            initial_quality=initial_quality,
            repair_passes=repair_passes,
            backend_errors=backend_errors,
        )
