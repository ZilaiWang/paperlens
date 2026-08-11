"""Research domain models (改进方案1 §十二-十四 / 改进方案2 Phase G §40-43)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ProjectStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class Project(BaseModel):
    """A research project: the top-level container."""

    model_config = ConfigDict(extra="allow")

    project_id: str
    workspace_id: str = ""
    name: str = ""
    description: str = ""
    goal: str = ""

    paper_ids: list[str] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)

    status: ProjectStatus = ProjectStatus.ACTIVE
    created_at: str = ""
    updated_at: str = ""


class ResearchQuestionStatus(str, Enum):
    OPEN = "OPEN"
    ANSWERING = "ANSWERING"
    ANSWERED = "ANSWERED"
    CLOSED = "CLOSED"


class ResearchQuestion(BaseModel):
    """One research question in a project."""

    model_config = ConfigDict(extra="allow")

    question_id: str
    project_id: str
    workspace_id: str = ""
    text: str
    detail: str = ""
    scope: list[str] = Field(default_factory=list)   # paper ids
    related_questions: list[str] = Field(default_factory=list)

    status: ResearchQuestionStatus = ResearchQuestionStatus.OPEN
    answer: str = ""
    evidence: list[dict[str, str]] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class Insight(BaseModel):
    """A structured insight discovered during research."""

    model_config = ConfigDict(extra="allow")

    insight_id: str
    project_id: str
    question_id: str = ""
    title: str = ""
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    supporting_papers: list[str] = Field(default_factory=list)
    evidence: list[dict[str, str]] = Field(default_factory=list)
    created_at: str = ""


class HypothesisStatus(str, Enum):
    PROPOSED = "PROPOSED"
    TESTING = "TESTING"
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class Hypothesis(BaseModel):
    """A falsifiable claim derived from the research graph."""

    model_config = ConfigDict(extra="allow")

    hypothesis_id: str
    project_id: str
    question_id: str = ""
    statement: str
    rationale: str = ""
    predictions: list[str] = Field(default_factory=list)
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    supporting_evidence: list[dict[str, str]] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
