"""Synthesis: consensus, contradictions and gap analysis (方案2 §38).

After cells are filled, Synthesizer produces the ComparisonSynthesis:
- consensus: papers agree on a value/claim
- contradictions: papers disagree
- gaps: dimensions/papers where no data exists
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .models import ComparisonSet, ComparisonSynthesis


class GapAnalysis:
    """Find dimensions with missing data across papers."""

    def gaps(self, comparison: ComparisonSet) -> list[str]:
        gaps: list[str] = []
        dimensions = set(comparison.dimensions) | {
            c.name for c in comparison.custom_dimensions
        }
        for dimension in dimensions:
            cells = [
                c for c in comparison.cells if c.dimension == dimension
            ]
            missing = len(comparison.paper_version_ids) - len(
                {c.paper_version_id for c in cells if c.value is not None}
            )
            if missing > 0:
                gaps.append(f"{dimension}: {missing}/{len(comparison.paper_version_ids)} 篇未覆盖")
        return gaps


class ConsensusFinder:
    """Find dimensions where most papers give the same value."""

    def consensus(self, comparison: ComparisonSet) -> list[str]:
        findings: list[str] = []
        dimensions = set(comparison.dimensions) | {
            c.name for c in comparison.custom_dimensions
        }
        for dimension in dimensions:
            cells = [
                c for c in comparison.cells
                if c.dimension == dimension and c.value is not None
            ]
            if len(cells) < 2:
                continue
            by_value: dict[str, int] = {}
            for cell in cells:
                key = _stringify(cell.value)
                by_value[key] = by_value.get(key, 0) + 1
            top, count = max(by_value.items(), key=lambda item: item[1])
            if count >= max(2, (len(cells) + 1) // 2):
                findings.append(f"{dimension} 一致 ({top}) [{count} 篇]")
        return findings


class Synthesizer:
    """Drive the final synthesis (LLM when model available)."""

    def __init__(
        self,
        *,
        model: object | None = None,
        gap_analysis: GapAnalysis | None = None,
        consensus: ConsensusFinder | None = None,
    ):
        self.model = model
        self.gap_analysis = gap_analysis or GapAnalysis()
        self.consensus = consensus or ConsensusFinder()

    def synthesize(
        self,
        comparison: ComparisonSet,
        *,
        stage: str = "comparison_synthesis",
        thread_id: str = "",
    ) -> ComparisonSynthesis:
        gaps = self.gap_analysis.gaps(comparison)
        consensus = self.consensus.consensus(comparison)

        synthesis = ComparisonSynthesis(
            consensus=consensus,
            gaps=gaps,
        )

        if self.model is not None and comparison.cells:
            response = self.model.invoke_json(
                system=(
                    "Summarize this comparison matrix. Return JSON: summary, "
                    "contradictions[], gaps[], consensus[]."
                ),
                user=self._render_matrix(comparison),
                schema=_SynthesisSchema,
                stage=stage,
                thread_id=thread_id,
            )
            synthesis.summary = response.summary
            synthesis.contradictions = list(response.contradictions)
            synthesis.consensus = list(response.consensus or consensus)
            synthesis.gaps = list(response.gaps or gaps)

        return synthesis

    def _render_matrix(self, comparison: ComparisonSet) -> str:
        lines = [f"QUESTION: {comparison.question}"]
        for dimension in list(comparison.dimensions) + [c.name for c in comparison.custom_dimensions]:
            cells = [c for c in comparison.cells if c.dimension == dimension]
            if not cells:
                continue
            lines.append(f"\n## {dimension}")
            for cell in cells:
                lines.append(
                    f"- {cell.paper_version_id}: {_stringify(cell.value)}"
                    + (f" (quote: {cell.quote[:80]})" if cell.quote else "")
                )
        return "\n".join(lines)


def _stringify(value: object) -> str:
    if value is None:
        return "(none)"
    return str(value)


class _SynthesisSchema(BaseModel):
    summary: str = ""
    contradictions: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    consensus: list[str] = Field(default_factory=list)
