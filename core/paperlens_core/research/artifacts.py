"""Research artifacts: kept outputs (notes / comparisons / reports)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ArtifactKind(str, Enum):
    NOTE = "NOTE"
    COMPARISON = "COMPARISON"
    REPORT = "REPORT"
    EXPERIMENT_RUN = "EXPERIMENT_RUN"
    AGENT_RUN = "AGENT_RUN"


class ResearchArtifact(BaseModel):
    """A kept research output inside a project."""

    model_config = ConfigDict(extra="allow")

    artifact_id: str
    project_id: str
    workspace_id: str = ""
    kind: ArtifactKind = ArtifactKind.NOTE
    title: str = ""
    content: str = ""
    source_type: str = ""        # comparison_set / agent_run / manual
    source_id: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


def artifact_from_text(
    *,
    artifact_id: str,
    project_id: str,
    title: str,
    content: str,
    kind: ArtifactKind = ArtifactKind.NOTE,
    workspace_id: str = "",
    created_at: str = "",
) -> ResearchArtifact:
    return ResearchArtifact(
        artifact_id=artifact_id,
        project_id=project_id,
        workspace_id=workspace_id,
        kind=kind,
        title=title,
        content=content,
        created_at=created_at,
    )
