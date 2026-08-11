"""Project service: create/update projects and their research items.

Decoupled from HTTP: takes plain dicts, returns domain models.  All
workspace scoping happens here so routes cannot leak across workspaces.
"""

from __future__ import annotations

from paperlens_core.ir.identity import new_id
from paperlens_core.research.models import (
    Hypothesis,
    Insight,
    Project,
    ResearchQuestion,
)

from ..repositories import VNextRepository
from ..repository import now_iso


class ProjectService:
    def __init__(self, repository: VNextRepository):
        self.repository = repository

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    def create_project(self, *, workspace_id: str, name: str, description: str = "", goal: str = "") -> Project:
        created = now_iso()
        project = Project(
            project_id=new_id("prj"),
            workspace_id=workspace_id,
            name=name,
            description=description,
            goal=goal,
            created_at=created,
            updated_at=created,
        )
        self.repository.save_project(project)
        return project

    def update_project(self, project_id: str, *, name: str | None = None, description: str | None = None, goal: str | None = None) -> Project | None:
        project = self.repository.get_project(project_id)
        if project is None:
            return None
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if goal is not None:
            project.goal = goal
        project.updated_at = now_iso()
        self.repository.save_project(project)
        return project

    def add_paper(self, project_id: str, paper_id: str) -> Project | None:
        project = self.repository.get_project(project_id)
        if project is None:
            return None
        if paper_id not in project.paper_ids:
            project.paper_ids.append(paper_id)
            project.updated_at = now_iso()
            self.repository.save_project(project)
        return project

    def list_projects(self, workspace_id: str) -> list[Project]:
        return self.repository.list_projects(workspace_id)

    def delete_project(self, project_id: str) -> None:
        self.repository.delete_project(project_id)

    # ------------------------------------------------------------------
    # Questions
    # ------------------------------------------------------------------
    def create_question(self, *, workspace_id: str, project_id: str, text: str, detail: str = "") -> ResearchQuestion:
        question = ResearchQuestion(
            question_id=new_id("q"),
            workspace_id=workspace_id,
            project_id=project_id,
            text=text,
            detail=detail,
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        self.repository.save_question(question)
        return question

    def list_questions(self, project_id: str) -> list[ResearchQuestion]:
        return self.repository.list_questions(project_id)

    # ------------------------------------------------------------------
    # Hypotheses
    # ------------------------------------------------------------------
    def create_hypothesis(self, *, workspace_id: str, project_id: str, question_id: str = "", statement: str, rationale: str = "") -> Hypothesis:
        hypothesis = Hypothesis(
            hypothesis_id=new_id("hyp"),
            workspace_id=workspace_id,
            project_id=project_id,
            question_id=question_id,
            statement=statement,
            rationale=rationale,
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        self.repository.save_hypothesis(hypothesis)
        return hypothesis

    def list_hypotheses(self, project_id: str) -> list[Hypothesis]:
        return self.repository.list_hypotheses(project_id)

    # ------------------------------------------------------------------
    # Insights
    # ------------------------------------------------------------------
    def create_insight(self, *, workspace_id: str, project_id: str, question_id: str = "", title: str, content: str) -> Insight:
        insight = Insight(
            insight_id=new_id("ins"),
            workspace_id=workspace_id,
            project_id=project_id,
            question_id=question_id,
            title=title,
            content=content,
            created_at=now_iso(),
        )
        self.repository.save_insight(insight)
        return insight

    def list_insights(self, project_id: str) -> list[Insight]:
        return self.repository.list_insights(project_id)
