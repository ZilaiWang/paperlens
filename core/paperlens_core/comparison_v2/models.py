"""ComparisonSet data models (改进方案2 Phase F §33-36)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ComparisonStatus(str, Enum):
    DRAFT = "DRAFT"
    EXTRACTING = "EXTRACTING"
    READY = "READY"
    SYNTHESIZED = "SYNTHESIZED"


class ComparisonVersion(BaseModel):
    """Version snapshot for one paper inside a ComparisonSet."""

    model_config = ConfigDict(extra="allow")

    paper_version_id: str
    profile_built_at: str = ""
    profile_status: str = "DRAFT"


class ComparisonCell(BaseModel):
    """One (dimension x paper) cell with evidence links."""

    model_config = ConfigDict(extra="allow")

    paper_version_id: str
    dimension: str
    value: object = None
    quote: str = ""
    evidence: list[dict[str, str]] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ComparisonSynthesis(BaseModel):
    """Gap analysis / consensus / contradiction summary."""

    model_config = ConfigDict(extra="allow")

    summary: str = ""
    consensus: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    by_dimension: dict[str, str] = Field(default_factory=dict)
    generated_at: str = ""


class ComparisonSet(BaseModel):
    """A saved comparison project (方案2 §33)."""

    model_config = ConfigDict(extra="allow")

    comparison_id: str
    workspace_id: str = ""
    name: str = ""
    description: str = ""

    # the driving research question
    question: str = ""

    # papers are pinned by version id (so re-parses don't break the set)
    paper_ids: list[str] = Field(default_factory=list)
    paper_version_ids: list[str] = Field(default_factory=list)
    versions: dict[str, ComparisonVersion] = Field(default_factory=dict)

    dimensions: list[str] = Field(
        default_factory=lambda: [
            "problem",
            "method",
            "experiments",
            "result_summary",
        ]
    )
    custom_dimensions: list["CustomDimension"] = Field(default_factory=list)

    cells: list[ComparisonCell] = Field(default_factory=list)
    synthesis: ComparisonSynthesis = Field(default_factory=ComparisonSynthesis)

    status: ComparisonStatus = ComparisonStatus.DRAFT
    created_at: str = ""
    updated_at: str = ""

    def ensure_paper(self, paper_id: str, paper_version_id: str) -> None:
        if paper_id not in self.paper_ids:
            self.paper_ids.append(paper_id)
        if paper_version_id not in self.paper_version_ids:
            self.paper_version_ids.append(paper_version_id)
        self.versions[paper_version_id] = ComparisonVersion(
            paper_version_id=paper_version_id
        )


# late import to avoid cycle (CustomDimension lives in extraction.py)
from .extraction import CustomDimension  # noqa: E402
