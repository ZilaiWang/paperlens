"""ParseCandidate: the universal intermediate representation (改进方案2 §15-16).

Every parser outputs candidates; only the canonicalizer turns them into
CanonicalNode.  Candidate ids are parse-scoped and never leak to the business
layer.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CandidateKind(str, Enum):
    PARAGRAPH = "PARAGRAPH"
    HEADING = "HEADING"
    SECTION = "SECTION"
    CAPTION = "CAPTION"
    FIGURE = "FIGURE"
    TABLE = "TABLE"
    TABLE_CELL = "TABLE_CELL"
    FORMULA = "FORMULA"
    REFERENCE = "REFERENCE"
    OTHER = "OTHER"


class ParseCandidate(BaseModel):
    """One node-shaped output of one backend, before canonization."""

    model_config = ConfigDict(extra="allow")

    candidate_id: str
    parse_run_id: str = ""
    backend: str
    backend_version: str = ""

    page: int
    kind: CandidateKind = CandidateKind.PARAGRAPH
    text: str = ""
    bbox: tuple[float, float, float, float] | None = None

    reading_order_hint: int | None = None
    parent_hint: str | None = None

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")
