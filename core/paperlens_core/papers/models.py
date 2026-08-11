"""PaperProfile data models (改进方案2 Phase E §28-31)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ProfileSection(str, Enum):
    PROBLEM = "PROBLEM"
    METHOD = "METHOD"
    EXPERIMENT = "EXPERIMENT"


class ProblemStatement(BaseModel):
    """The research problem the paper addresses."""

    model_config = ConfigDict(extra="allow")

    problem: str = ""
    motivation: str = ""
    challenges: list[str] = Field(default_factory=list)
    research_questions: list[str] = Field(default_factory=list)
    prior_limitations: list[str] = Field(default_factory=list)


class MethodBlock(BaseModel):
    """One method module with design choices."""

    model_config = ConfigDict(extra="allow")

    name: str = ""
    role: str = ""               # e.g. "feature extractor"
    summary: str = ""
    design_choices: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    # which sections/pages support this block (for Evidence Inspector)
    evidence: list[dict[str, str]] = Field(default_factory=list)


class ExperimentResult(BaseModel):
    """One quantitative result row."""

    model_config = ConfigDict(extra="allow")

    metric: str = ""
    dataset: str = ""
    value: float | None = None
    unit: str = ""
    comparison_baseline: str = ""
    paper_says: str = ""         # raw text from the paper


class ExperimentRecord(BaseModel):
    """One experiment (table row or paragraph) with full context."""

    model_config = ConfigDict(extra="allow")

    experiment_id: str = ""
    setup: str = ""
    datasets: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    results: list[ExperimentResult] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    # for comparability with other papers
    comparability_key: dict[str, str] = Field(default_factory=dict)
    source_evidence: list[dict[str, str]] = Field(default_factory=list)


class PaperProfile(BaseModel):
    """Structured digest of one paper."""

    model_config = ConfigDict(extra="allow")

    paper_version_id: str = ""
    paper_id: str = ""

    title: str = ""
    abstract: str = ""
    domain: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    problem: ProblemStatement = Field(default_factory=ProblemStatement)
    method: list[MethodBlock] = Field(default_factory=list)
    experiments: list[ExperimentRecord] = Field(default_factory=list)

    abbreviations: list[dict[str, str]] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)

    version: str = "1.0"
    built_at: str = ""
    status: str = "DRAFT"        # DRAFT | COMPLETE

    def summary(self) -> str:
        parts = [f"# {self.title}"]
        if self.problem.problem:
            parts.append(f"问题: {self.problem.problem[:160]}")
        if self.method:
            parts.append(f"方法: {'; '.join(m.name for m in self.method[:5])}")
        if self.experiments:
            parts.append(f"实验: {len(self.experiments)} 个实验记录")
        return "\n".join(parts)
