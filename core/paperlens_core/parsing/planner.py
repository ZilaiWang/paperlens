"""ParsePlanner: turns a ProbeReport into an ordered parse plan (改进方案1 §三).

The plan assigns each document region to a backend, ordered by preference and
capability, so the pipeline no longer does "whole-page pick A or B" — tables,
formulas and body text can be handled by different backends.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .contracts import Capability, ParseRegion


class PlanStep(BaseModel):
    """One backend execution in the plan."""

    model_config = ConfigDict(extra="allow")

    region: ParseRegion
    backend: str
    # fallback backends tried if this one fails
    fallbacks: list[str] = Field(default_factory=list)
    page_range: tuple[int, int] | None = None
    required: bool = True
    weight: float = 1.0  # how much this region matters for overall quality


class ParsePlan(BaseModel):
    """Ordered list of region→backend assignments."""

    model_config = ConfigDict(extra="allow")

    document_type: str = "UNKNOWN"
    layout: str = "UNKNOWN"
    steps: list[PlanStep] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ParsePlanner:
    """Default planner: maps probe signals onto backend capabilities."""

    def __init__(self, backends: list[object], *, prefer: str | None = None):
        self.backends = backends
        self.prefer = prefer

    def _backend_by_capability(
        self, capability: Capability, available: set[str] | None = None
    ) -> list[str]:
        order: list[str] = []
        for backend in self.backends:
            try:
                caps = backend.capabilities()
            except Exception:  # noqa: BLE001 - planner is defensive
                continue
            name = getattr(backend, "name", type(backend).__name__)
            if capability in caps and (available is None or name in available):
                order.append(name)
        if self.prefer and order and order[0] != self.prefer:
            # move preferred to front (stable)
            order = [self.prefer] + [b for b in order if b != self.prefer]
        return order

    def plan(self, probe: object) -> ParsePlan:
        report = probe
        document_type = getattr(report, "document_type", "UNKNOWN")
        layout = getattr(report, "layout", "UNKNOWN")
        table_complexity = getattr(report, "table_complexity", "LOW")
        ocr_required = bool(getattr(report, "ocr_required", False))
        available_names = set(getattr(report, "available_backends", []) or []) or None

        # body text: prefer a text+layout backend. OCR/VLM providers are held
        # back for selective repair and must never become an automatic full
        # document pass merely because they also declare LAYOUT.
        ocr_backends = self._backend_by_capability(Capability.OCR, available_names)
        body_backends = self._backend_by_capability(Capability.LAYOUT, available_names)
        body_backends = body_backends or self._backend_by_capability(Capability.TEXT, available_names)
        body_backends = [name for name in body_backends if name not in ocr_backends]
        body_fallbacks = [b for b in body_backends[1:]] if body_backends else []

        # OCR/VLM stays out of every initial full-document capability pass.
        # It is intentionally reserved for RepairPlanner page ranges.
        table_backends = [
            name
            for name in self._backend_by_capability(Capability.TABLE, available_names)
            if name not in ocr_backends
        ]
        table_fallbacks = [b for b in table_backends[1:]] or body_backends[:1]

        formula_backends = [
            name
            for name in self._backend_by_capability(Capability.FORMULA, available_names)
            if name not in ocr_backends
        ]

        # references
        bib_backends = self._backend_by_capability(Capability.BIBLIOGRAPHY, available_names)

        steps: list[PlanStep] = []
        scheduled: set[str] = set()
        for index, backend in enumerate(body_backends):
            steps.append(
                PlanStep(
                    region=ParseRegion.BODY_TEXT,
                    backend=backend,
                    fallbacks=body_fallbacks if index == 0 else [],
                    required=index == 0,
                    weight=1.0 if index == 0 else 0.8,
                )
            )
            scheduled.add(backend)
        table_provider = next((name for name in table_backends if name not in scheduled), "")
        if table_provider:
            steps.append(
                PlanStep(
                    region=ParseRegion.TABLE,
                    backend=table_provider,
                    fallbacks=table_fallbacks,
                    required=table_complexity != "LOW",
                    weight=0.4,
                )
            )
            scheduled.add(table_provider)
        formula_provider = next((name for name in formula_backends if name not in scheduled), "")
        if formula_provider:
            steps.append(
                PlanStep(
                    region=ParseRegion.FORMULA,
                    backend=formula_provider,
                    fallbacks=formula_backends[1:],
                    required=False,
                    weight=0.2,
                )
            )
            scheduled.add(formula_provider)
        if bib_backends:
            bibliography_provider = next(
                (name for name in bib_backends if name not in scheduled), ""
            )
        else:
            bibliography_provider = ""
        if bibliography_provider:
            steps.append(
                PlanStep(
                    region=ParseRegion.BIBLIOGRAPHY,
                    backend=bibliography_provider,
                    fallbacks=bib_backends[1:],
                    required=False,
                    weight=0.3,
                )
            )
        # OCR/VLM is a repair capability. It is deliberately not scheduled as
        # a full-document pass; RepairPlanner selects only low-quality pages.
        if ocr_required and ocr_backends:
            notes = list(getattr(report, "notes", []))
            notes.append(f"OCR repair available: {ocr_backends[0]}")
        else:
            notes = list(getattr(report, "notes", []))

        if ocr_required:
            notes.append("OCR required — 无 OCR 后端时正文质量受限")

        return ParsePlan(
            document_type=document_type,
            layout=layout,
            steps=steps,
            notes=notes,
        )
