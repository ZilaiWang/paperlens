"""Validated request models for the public HTTP API.

Keeping transport contracts separate from route implementations makes the
generated OpenAPI document reliable and prevents endpoint-local models from
being accidentally omitted during refactors.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


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
