"""Validated request models for the public HTTP API.

Keeping transport contracts separate from route implementations makes the
generated OpenAPI document reliable and prevents endpoint-local models from
being accidentally omitted during refactors.
"""

from __future__ import annotations

from paperlens_core.autoresearch.experiment import RunKind
from paperlens_core.termbase import TermEntryUpsert
from pydantic import BaseModel, ConfigDict, Field


class ArxivImportRequest(BaseModel):
    arxiv_input: str = Field(min_length=5, max_length=200)


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    context: str = "whole_paper"
    context_block_ids: list[str] = Field(default_factory=list)
    task_id: str = ""


class ResolveRequest(BaseModel):
    contact_email: str = ""


class ComparisonRequest(BaseModel):
    paper_version_ids: list[str] = Field(min_length=2, max_length=3)
    dimensions: list[str] = Field(default_factory=list, max_length=13)


class ComparisonQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=800)
    history: list[dict[str, str]] = Field(default_factory=list)


class TranslateRequest(BaseModel):
    page: int | None = None
    pages: list[int] | None = None
    section_id: str | None = None
    rebuild: bool = False


class AnnotationRequest(BaseModel):
    block_id: str = ""
    char_start: int = 0
    char_end: int = 0
    kind: str = "HIGHLIGHT"
    text: str = ""


# vNext transport contracts -------------------------------------------------
class WorkspaceCreateRequest(BaseModel):
    name: str = ""


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    goal: str = ""


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    description: str | None = None
    goal: str | None = None


class ProjectPaperRequest(BaseModel):
    paper_id: str = Field(min_length=1, max_length=200)


class QuestionCreateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=800)
    detail: str = ""


class HypothesisCreateRequest(BaseModel):
    question_id: str = ""
    statement: str = Field(min_length=1, max_length=1000)
    rationale: str = ""


class RunCreateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    paper_version_ids: list[str] = Field(default_factory=list)


class CustomDimensionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    instruction: str = ""


class ComparisonSetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    question: str = ""
    paper_version_ids: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    custom_dimensions: list[CustomDimensionRequest] = Field(default_factory=list)


class TermUpsertRequest(TermEntryUpsert):
    """Workspace-owned term entry request."""


class TranslateV2Request(BaseModel):
    model_config = ConfigDict(extra="allow")

    paragraphs: list[str] = Field(min_length=1, max_length=200)
    section_title: str = ""
    paper_title: str = ""


class TermScanRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class ExperimentPlanRequest(BaseModel):
    kind: RunKind = RunKind.SCRIPT
    command: str = ""
    description: str = ""
    parameters: dict[str, object] = Field(default_factory=dict)
