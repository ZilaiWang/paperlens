"""RepairPlanner: re-run only the failing pages/regions (改进方案1 §三 / §五).

QualityInspector flags pages; the repair planner submits a narrow re-parse for
those pages with an alternative backend, then merges the repaired nodes back
into the document (replacing the old revisions).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RepairTarget(BaseModel):
    model_config = ConfigDict(extra="allow")

    page: int
    reason: str = ""
    alternative_backend: str = ""
    attempted: bool = False
    repaired: bool = False


class RepairPlan(BaseModel):
    model_config = ConfigDict(extra="allow")

    targets: list[RepairTarget] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    passes: int = 0


class RepairPlanner:
    """Decide which pages need repair and which backend to retry with."""

    def __init__(self, backend_names: list[str]):
        self.backend_names = list(backend_names)

    def plan(
        self,
        quality_report: object,
        *,
        primary_backend: str,
        max_pages: int = 20,
    ) -> RepairPlan:
        report = quality_report
        page_quality = getattr(report, "page_quality", {})
        alternatives = [b for b in self.backend_names if b != primary_backend]
        # Visual parsing is expensive and is reserved for pages that failed
        # the primary structure/text parse.
        alternatives.sort(key=lambda name: (name != "paddleocr-vl", name))
        if not alternatives:
            alternatives = self.backend_names[:1]

        targets: list[RepairTarget] = []
        low_pages = [p for p, q in page_quality.items() if q in ("LOW", "SUSPECT")]
        for page in sorted(low_pages)[:max_pages]:
            reason = f"page quality {page_quality[page]}"
            targets.append(
                RepairTarget(
                    page=page,
                    reason=reason,
                    alternative_backend=alternatives[0],
                )
            )
        return RepairPlan(targets=targets)
