"""ExperimentRun: record and analyze auto-research executions (方案2 §49-50).

The bridge does not run external experiments; it records their plan,
inputs/outputs, and produces ResultAnalysis for the research workspace.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RunKind(str, Enum):
    SCRIPT = "SCRIPT"
    NOTEBOOK = "NOTEBOOK"
    SERVICE = "SERVICE"
    MANUAL = "MANUAL"


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ExperimentPlan(BaseModel):
    """What the external runtime plans to run."""

    model_config = ConfigDict(extra="allow")

    run_id: str = ""
    kind: RunKind = RunKind.SCRIPT
    command: str = ""
    description: str = ""
    parameters: dict[str, object] = Field(default_factory=dict)
    inputs: list[str] = Field(default_factory=list)   # referenced pack/artifact ids
    expected_outputs: list[str] = Field(default_factory=list)


class ExperimentRun(BaseModel):
    """One recorded execution."""

    model_config = ConfigDict(extra="allow")

    run_id: str
    workspace_id: str = ""
    project_id: str = ""
    pack_id: str = ""
    plan: ExperimentPlan = Field(default_factory=ExperimentPlan)

    status: RunStatus = RunStatus.PLANNED
    started_at: str = ""
    finished_at: str = ""
    stdout: str = ""
    exit_code: int | None = None
    artifacts_produced: list[str] = Field(default_factory=list)
    error: str = ""


class ResultAnalysis(BaseModel):
    """Analysis of a completed run, stored back into the workspace."""

    model_config = ConfigDict(extra="allow")

    analysis_id: str = ""
    run_id: str
    verdict: str = ""           # SUPPORTED | REFUTED | INCONCLUSIVE | INFO
    summary: str = ""
    key_metrics: list[dict[str, object]] = Field(default_factory=list)
    related_hypotheses: list[str] = Field(default_factory=list)
    created_at: str = ""


def create_experiment_run(
    *,
    run_id: str,
    workspace_id: str,
    project_id: str,
    pack_id: str = "",
    plan: ExperimentPlan | None = None,
    started_at: str = "",
) -> ExperimentRun:
    return ExperimentRun(
        run_id=run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        pack_id=pack_id,
        plan=plan or ExperimentPlan(run_id=run_id),
        started_at=started_at,
    )


def analyze_run_results(
    *,
    run: ExperimentRun,
    verdict: str,
    summary: str,
    key_metrics: list[dict[str, object]] | None = None,
    related_hypotheses: list[str] | None = None,
    created_at: str = "",
) -> ResultAnalysis:
    """Build a ResultAnalysis from a completed run."""
    return ResultAnalysis(
        analysis_id=f"ana-{run.run_id[:8]}",
        run_id=run.run_id,
        verdict=verdict,
        summary=summary,
        key_metrics=key_metrics or [],
        related_hypotheses=related_hypotheses or [],
        created_at=created_at,
    )
