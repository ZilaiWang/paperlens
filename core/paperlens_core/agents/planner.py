"""TaskPlanner: turn a research question into a run DAG (改进方案2 Phase H §45).

The default planner produces a deterministic, dependency-ordered plan
(plan → retrieve → profile → compare → synthesize → produce).  A model-backed
planner can reorder/extend it, but the executor only understands this shape,
so the DAG is always executable.
"""

from __future__ import annotations

from typing import Callable

from .adaptive import DepthRouter
from .models import (
    AnalysisDepth,
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


def create_adaptive_run_plan(
    *,
    run_id: str,
    workspace_id: str,
    project_id: str,
    question: str,
    scope_paper_ids: list[str],
    created_at: str = "",
    depth: AnalysisDepth | None = None,
) -> ResearchRun:
    """Create a bounded 3–8 task plan selected from paper capabilities."""
    routed = DepthRouter().route(question)
    resolved_depth = depth or routed.depth
    tasks: list[TaskDefinition] = []

    def add(task_id: str, name: str, tool: str, capability: str, specialist: str, deps=()):
        tasks.append(
            TaskDefinition(
                task_id=task_id,
                run_id=run_id,
                task_type=TaskType.RETRIEVE if tool else TaskType.SYNTHESIZE,
                name=name,
                tool=tool,
                capability=capability,
                specialist=specialist,
                params={"query": question, "paper_ids": scope_paper_ids, "top_k": 6},
                dependencies=[TaskDependency(task_id=item) for item in deps],
                description=f"{capability} capability",
            )
        )

    add("t-evidence", "定位直接证据", "search_evidence", "evidence.search", "evidence")
    intent_tasks = {
        "METHOD": ("t-method", "梳理方法结构", "inspect_method", "method.inspect", "method"),
        "EXPERIMENT": ("t-experiment", "核对实验设计", "inspect_experiments", "experiment.inspect", "experiment"),
        "REPRODUCTION": ("t-reproduction", "检查复现信息", "inspect_reproduction", "reproduction.inspect", "reproduction"),
        "CRITICAL": ("t-critical", "寻找限制与反证", "critical_review", "critical.review", "critic"),
        "FORMULA": ("t-formula", "解释公式与符号", "inspect_formula", "document.formula", "method"),
        "GENERAL": ("t-structure", "理解所在章节", "inspect_document", "document.inspect", "reader"),
    }
    task = intent_tasks[routed.intent]
    add(*task, deps=("t-evidence",))

    previous = task[0]
    if resolved_depth in (AnalysisDepth.ANALYTIC, AnalysisDepth.DEEP):
        experiment_id = (
            "t-experiment-cross"
            if any(item.task_id == "t-experiment" for item in tasks)
            else "t-experiment"
        )
        add(experiment_id, "交叉检查实验依据", "inspect_experiments", "experiment.inspect", "experiment", (previous,))
        previous = experiment_id
    if resolved_depth == AnalysisDepth.DEEP:
        reproduction_id = (
            "t-reproduction-detail"
            if any(item.task_id == "t-reproduction" for item in tasks)
            else "t-reproduction"
        )
        add(reproduction_id, "检查复现条件", "inspect_reproduction", "reproduction.inspect", "reproduction", (previous,))
        add("t-critic", "验证结论与边界", "critical_review", "critical.review", "critic", (reproduction_id,))
        previous = "t-critic"

    tasks.append(
        TaskDefinition(
            task_id="t-synthesize",
            run_id=run_id,
            task_type=TaskType.SYNTHESIZE,
            name="综合证据",
            dependencies=[TaskDependency(task_id="t-evidence"), TaskDependency(task_id=previous)],
            capability="answer.synthesize",
            specialist="synthesizer",
        )
    )
    tasks.append(
        TaskDefinition(
            task_id="t-produce",
            run_id=run_id,
            task_type=TaskType.PRODUCE,
            name="形成回答",
            dependencies=[TaskDependency(task_id="t-synthesize")],
            capability="answer.produce",
            specialist="synthesizer",
        )
    )
    return ResearchRun(
        run_id=run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        question=question,
        depth=resolved_depth,
        intent=routed.intent,
        tasks=tasks[:8],
        status=RunStatus.PLANNED,
        artifact=ArtifactProduced(title=question[:60]),
        created_at=created_at,
        notes=[f"DepthRouter: {resolved_depth.value} — {routed.reason}"],
    )
