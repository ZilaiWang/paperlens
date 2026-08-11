"""Offline AgentBench for routing, plan bounds and evidence-bearing findings."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .adaptive import DepthRouter
from .models import AnalysisDepth
from .planner import create_adaptive_run_plan


class AgentBenchCase(BaseModel):
    question: str
    expected_depth: AnalysisDepth
    expected_intent: str = ""


class AgentBenchReport(BaseModel):
    total: int = 0
    depth_accuracy: float = 0.0
    intent_accuracy: float = 0.0
    bounded_plan_ratio: float = 0.0
    failures: list[str] = Field(default_factory=list)


def run_agent_bench(cases: list[AgentBenchCase]) -> AgentBenchReport:
    router = DepthRouter()
    depth_ok = intent_ok = bounded = 0
    failures: list[str] = []
    for index, case in enumerate(cases):
        routed = router.route(case.question)
        if routed.depth == case.expected_depth:
            depth_ok += 1
        else:
            failures.append(f"case {index}: depth {routed.depth.value} != {case.expected_depth.value}")
        if not case.expected_intent or routed.intent == case.expected_intent:
            intent_ok += 1
        run = create_adaptive_run_plan(
            run_id=f"bench-{index}",
            workspace_id="bench",
            project_id="",
            question=case.question,
            scope_paper_ids=["paper"],
        )
        if 3 <= len(run.tasks) <= 8 and len({task.task_id for task in run.tasks}) == len(run.tasks):
            bounded += 1
        else:
            failures.append(f"case {index}: invalid task plan")
    total = len(cases)
    return AgentBenchReport(
        total=total,
        depth_accuracy=round(depth_ok / total, 3) if total else 0.0,
        intent_accuracy=round(intent_ok / total, 3) if total else 0.0,
        bounded_plan_ratio=round(bounded / total, 3) if total else 0.0,
        failures=failures,
    )
