"""ResearchContextPack (改进方案2 Phase I §48).

A versioned, portable pack of everything an external research runtime needs:
project goal, questions, hypotheses, papers (with versions), and any saved
artifacts.  Built deterministically from a project's data.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PaperContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    paper_id: str
    paper_version_id: str
    title: str = ""
    abstract: str = ""
    url: str = ""


class ResearchContextPack(BaseModel):
    """Portable snapshot of a research project for external runtimes."""

    model_config = ConfigDict(extra="allow")

    pack_id: str
    version: str = "1.0"

    workspace_id: str = ""
    project_id: str = ""
    project_name: str = ""
    goal: str = ""

    questions: list[str] = Field(default_factory=list)
    hypotheses: list[dict[str, str]] = Field(default_factory=list)  # {id, statement, status}
    papers: list[PaperContext] = Field(default_factory=list)
    artifacts: list[dict[str, object]] = Field(default_factory=list)

    created_at: str = ""

    def as_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


def build_research_context_pack(
    *,
    pack_id: str,
    workspace_id: str,
    project_id: str,
    project_name: str,
    goal: str,
    questions: list[str] | None = None,
    hypotheses: list[dict[str, str]] | None = None,
    papers: list[PaperContext] | None = None,
    artifacts: list[dict[str, object]] | None = None,
    created_at: str = "",
) -> ResearchContextPack:
    return ResearchContextPack(
        pack_id=pack_id,
        workspace_id=workspace_id,
        project_id=project_id,
        project_name=project_name,
        goal=goal,
        questions=questions or [],
        hypotheses=hypotheses or [],
        papers=papers or [],
        artifacts=artifacts or [],
        created_at=created_at,
    )


def pack_from_project(
    *,
    project: object,
    questions: list[object] | None = None,
    hypotheses: list[object] | None = None,
    papers: list[object] | None = None,
    artifacts: list[object] | None = None,
    created_at: str = "",
) -> ResearchContextPack:
    """Build a pack from research/ domain models (decoupled via duck typing)."""
    questions = questions or []
    hypotheses = hypotheses or []
    papers = papers or []
    artifacts = artifacts or []

    return ResearchContextPack(
        pack_id=f"pack-{getattr(project, 'project_id', 'unknown')[:12]}",
        workspace_id=getattr(project, "workspace_id", ""),
        project_id=getattr(project, "project_id", ""),
        project_name=getattr(project, "name", ""),
        goal=getattr(project, "goal", ""),
        questions=[q.text for q in questions if hasattr(q, "text")],
        hypotheses=[
            {
                "id": getattr(h, "hypothesis_id", ""),
                "statement": getattr(h, "statement", ""),
                "status": getattr(getattr(h, "status", ""), "value", str(getattr(h, "status", ""))),
            }
            for h in hypotheses
        ],
        papers=[
            PaperContext(
                paper_id=getattr(p, "paper_id", ""),
                paper_version_id=getattr(p, "paper_version_id", ""),
                title=getattr(p, "title", ""),
                abstract=getattr(p, "abstract", ""),
            )
            for p in papers
        ],
        artifacts=[
            {
                "artifact_id": getattr(a, "artifact_id", ""),
                "title": getattr(a, "title", ""),
                "content": getattr(a, "content", ""),
            }
            for a in artifacts
        ],
        created_at=created_at,
    )
