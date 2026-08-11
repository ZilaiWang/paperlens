"""Research Agent data models (改进方案1 §十五 / 改进方案2 Phase H §44-45)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class TaskType(str, Enum):
    PLAN = "PLAN"
    RETRIEVE = "RETRIEVE"
    PROFILE = "PROFILE"
    COMPARE = "COMPARE"
    SYNTHESIZE = "SYNTHESIZE"
    PRODUCE = "PRODUCE"     # artifact
    VERIFY = "VERIFY"


class AnalysisDepth(str, Enum):
    QUICK = "QUICK"
    ANALYTIC = "ANALYTIC"
    DEEP = "DEEP"


class FindingKind(str, Enum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    ASSESSMENT = "ASSESSMENT"
    UNKNOWN = "UNKNOWN"


class RequirementState(str, Enum):
    SPECIFIED = "SPECIFIED"
    INFERRED = "INFERRED"
    MISSING = "MISSING"
    EXTERNAL = "EXTERNAL"


class ResearchFinding(BaseModel):
    """One evidence-bearing claim produced by the Paper Agent."""

    statement: str
    kind: FindingKind = FindingKind.FACT
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    caveats: list[str] = Field(default_factory=list)
    source_task_id: str = ""


class ReproductionRequirement(BaseModel):
    requirement: str
    state: RequirementState = RequirementState.MISSING
    value: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    children: list["ReproductionRequirement"] = Field(default_factory=list)


class TaskDependency(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_id: str
    result_key: str = ""     # which field of the upstream result this task needs


class TaskDefinition(BaseModel):
    """One node in the run DAG."""

    model_config = ConfigDict(extra="allow")

    task_id: str
    run_id: str = ""
    task_type: TaskType = TaskType.RETRIEVE
    name: str = ""
    tool: str = ""           # registered tool name, e.g. "search"
    params: dict[str, object] = Field(default_factory=dict)
    dependencies: list[TaskDependency] = Field(default_factory=list)
    description: str = ""
    capability: str = ""
    specialist: str = ""


class TaskResult(BaseModel):
    """Output of one task."""

    model_config = ConfigDict(extra="allow")

    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    ok: bool = False
    output: dict[str, object] = Field(default_factory=dict)
    error: str = ""
    duration_ms: int = 0


class ArtifactProduced(BaseModel):
    """An artifact created by the PRODUCE task."""

    model_config = ConfigDict(extra="allow")

    artifact_id: str = ""
    kind: str = "REPORT"
    title: str = ""
    content: str = ""
    references: list[str] = Field(default_factory=list)


class ResearchRun(BaseModel):
    """A full agent run over a research question."""

    model_config = ConfigDict(extra="allow")

    run_id: str
    workspace_id: str = ""
    project_id: str = ""
    question: str = ""
    depth: AnalysisDepth = AnalysisDepth.ANALYTIC
    intent: str = "GENERAL"

    tasks: list[TaskDefinition] = Field(default_factory=list)
    status: RunStatus = RunStatus.PLANNED

    artifact: ArtifactProduced | None = None
    findings: list[str] = Field(default_factory=list)
    structured_findings: list[ResearchFinding] = Field(default_factory=list)
    reproduction_requirements: list[ReproductionRequirement] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    created_at: str = ""
    updated_at: str = ""

    def task(self, task_id: str) -> TaskDefinition | None:
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        return None
