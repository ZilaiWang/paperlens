"""Selective Repair: re-translate only units that failed verification (改进方案2 §24 [6])."""

from __future__ import annotations

from dataclasses import dataclass, field

from .verifier import VerifyReport


@dataclass
class RepairCandidate:
    index: int
    source: str
    target: str
    issues: list[str] = field(default_factory=list)


class RepairPlanner:
    """Decide which units need repair and compose the repair instruction."""

    def __init__(self, *, max_repairs: int = 10):
        self.max_repairs = max_repairs

    def plan(self, reports: list[VerifyReport]) -> list[int]:
        """Return indices of units that failed verification (cap at max)."""
        failed = [
            index
            for index, report in enumerate(reports)
            if not report.passed and report.errors
        ]
        return failed[: self.max_repairs]

    def instruction(self, report: VerifyReport) -> str:
        """Turn verification issues into a targeted repair instruction."""
        parts = [f"{issue.kind}: {issue.detail}" for issue in report.errors]
        return "；".join(parts) if parts else ""
