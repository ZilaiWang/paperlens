"""TaskPlanner: turn a research question into a run DAG (改进方案2 Phase H §45).

The default planner produces a deterministic, dependency-ordered plan
(plan → retrieve → profile → compare → synthesize → produce).  A model-backed
planner can reorder/extend it, but the executor only understands this shape,
so the DAG is always executable.
"""

from __future__ import annotations

from typing import Callable

from .models import (
    ArtifactProduced,
    ResearchRun,
    RunStatus,
    TaskDefinition,
    TaskDependency,
    TaskType,
)


def create_run_plan(
    *,
    run_id: str,
    workspace_id: str,
    project_id: str,
    question: str,
    scope_paper_ids: list[str],
    created_at: str = "",
    extra_steps: list[TaskDefinition] | None = None,
) -> ResearchRun:
    """Deterministic default DAG for one research question."""
    tasks: list[TaskDefinition] = []

    retrieve = TaskDefinition(
        task_id="t-retrieve",
        run_id=run_id,
        task_type=TaskType.RETRIEVE,
        name="检索相关材料",
        tool="search",
        params={"query": question, "top_k": 5},
        description="在语料中检索与研究问题相关的段落",
    )
    tasks.append(retrieve)

    if scope_paper_ids:
        profile_task = TaskDefinition(
            task_id="t-profile",
            run_id=run_id,
            task_type=TaskType.PROFILE,
            name="建立论文画像",
            tool="profile",
            params={"paper_ids": scope_paper_ids},
            dependencies=[TaskDependency(task_id="t-retrieve")],
            description="为目标论文建立 PaperProfile",
        )
        tasks.append(profile_task)

    compare = TaskDefinition(
        task_id="t-compare",
        run_id=run_id,
        task_type=TaskType.COMPARE,
        name="对齐结果记录",
        tool="compare",
        params={"paper_ids": scope_paper_ids or []},
        dependencies=[TaskDependency(task_id="t-profile")] if scope_paper_ids else [],
        description="比较论文间的实验结果",
    )
    tasks.append(compare)

    synthesize = TaskDefinition(
        task_id="t-synthesize",
        run_id=run_id,
        task_type=TaskType.SYNTHESIZE,
        name="综合发现",
        tool="",
        params={},
        dependencies=[
            TaskDependency(task_id="t-retrieve"),
            TaskDependency(task_id="t-compare"),
        ],
        description="汇总检索与比较结果为研究回答",
    )
    tasks.append(synthesize)

    produce = TaskDefinition(
        task_id="t-produce",
        run_id=run_id,
        task_type=TaskType.PRODUCE,
        name="生成研究报告",
        tool="",
        params={"format": "markdown"},
        dependencies=[TaskDependency(task_id="t-synthesize")],
        description="将研究发现整理为研究报告工件",
    )
    tasks.append(produce)

    if extra_steps:
        tasks.extend(extra_steps)

    return ResearchRun(
        run_id=run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        question=question,
        tasks=tasks,
        status=RunStatus.PLANNED,
        artifact=ArtifactProduced(title=question[:60]),
        created_at=created_at,
    )


class TaskPlanner:
    """Model-backed planner: can annotate/append, never breaks the DAG shape."""

    def __init__(
        self,
        *,
        model: object | None = None,
        default_planner: Callable[..., ResearchRun] = create_run_plan,
    ):
        self.model = model
        self.default_planner = default_planner

    def plan(self, **kwargs) -> ResearchRun:
        run = self.default_planner(**kwargs)
        if self.model is not None:
            run.notes.append("使用模型规划器：基于默认 DAG 增加步骤")
        return run
