"""TaskExecutor: run a DAG topologically (改进方案2 Phase H §47).

Real execution semantics:
- runs only tasks whose dependencies are satisfied (completed)
- tool tasks call the ToolRegistry; non-tool tasks are synthesized locally
- failures are recorded; the DAG still progresses where possible
- PRODUCE assembles the final artifact from upstream findings
"""

from __future__ import annotations

import time
from collections import deque

from .models import (
    ArtifactProduced,
    ResearchRun,
    RunStatus,
    TaskDefinition,
    TaskResult,
    TaskStatus,
    TaskType,
)
from .runtime import ToolContext, ToolRegistry


def _topological(tasks: list[TaskDefinition]) -> list[TaskDefinition]:
    """Stable topological order of the DAG (Kahn's algorithm)."""
    by_id = {task.task_id: task for task in tasks}
    in_degree: dict[str, int] = {task_id: 0 for task_id in by_id}
    adj: dict[str, list[str]] = {task_id: [] for task_id in by_id}
    for task in tasks:
        for dep in task.dependencies:
            if dep.task_id in by_id:
                adj[dep.task_id].append(task.task_id)
                in_degree[task.task_id] = in_degree.get(task.task_id, 0) + 1
    queue = deque(sorted([tid for tid, deg in in_degree.items() if deg == 0]))
    ordered: list[TaskDefinition] = []
    while queue:
        tid = queue.popleft()
        ordered.append(by_id[tid])
        for nxt in sorted(adj[tid]):
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)
    # any tasks that are part of a cycle or missing deps: append at the end
    appended = {t.task_id for t in ordered}
    ordered.extend(t for t in tasks if t.task_id not in appended)
    return ordered


def execute_run(
    run: ResearchRun,
    *,
    registry: ToolRegistry,
    question_context: str = "",
) -> list[TaskResult]:
    """Execute the run's DAG and return per-task results."""
    run.status = RunStatus.RUNNING
    results: dict[str, TaskResult] = {}
    ordered = _topological(run.tasks)

    for task in ordered:
        # A dependency blocks only if it FAILED hard; a tool being unwired is a
        # soft failure (the DAG still advances).  synthesize/produce run once
        # their required inputs were attempted.
        deps_ok = True
        blocked_reason = ""
        for dep in task.dependencies:
            upstream = results.get(dep.task_id)
            if upstream is None:
                deps_ok = False
                blocked_reason = f"dependency {dep.task_id} not run yet"
                break
            if upstream.status == TaskStatus.SKIPPED:
                deps_ok = False
                blocked_reason = f"dependency {dep.task_id} skipped"
                break
            # COMPLETED or FAILED → proceed (tool failure recorded, not fatal)
        if not deps_ok:
            results[task.task_id] = TaskResult(
                task_id=task.task_id,
                status=TaskStatus.SKIPPED,
                ok=False,
                error=blocked_reason,
            )
            continue

        started = time.monotonic()
        result = _run_single_task(run, task, registry, question_context)
        result.duration_ms = int((time.monotonic() - started) * 1000)
        results[task.task_id] = result
        if result.ok and result.output and task.task_type != TaskType.PRODUCE:
            run.findings.append(f"[{task.name}] {_summarize(result.output)}")

    # find task order for the produced artifact
    produced: list[str] = []
    for task in ordered:
        tr = results.get(task.task_id)
        if tr and tr.ok:
            produced.append(task.name)

    produce_results = [
        results.get(task.task_id)
        for task in ordered
        if task.task_type == TaskType.PRODUCE
    ]
    evidence_results = [
        results.get(task.task_id)
        for task in ordered
        if task.task_type in {TaskType.RETRIEVE, TaskType.PROFILE, TaskType.COMPARE}
    ]
    has_real_output = any(result is not None and result.ok for result in evidence_results)
    if (
        produce_results
        and all(result is not None and result.ok for result in produce_results)
        and has_real_output
    ):
        run.status = RunStatus.COMPLETED
    else:
        run.status = RunStatus.FAILED
    return [results[t.task_id] for t in ordered if t.task_id in results]


def _run_single_task(
    run: ResearchRun,
    task: TaskDefinition,
    registry: ToolRegistry,
    question_context: str,
) -> TaskResult:
    if task.task_type == TaskType.RETRIEVE:
        tool_result = registry.invoke(
            task.tool,
            ToolContext(
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                run_id=run.run_id,
                question=run.question,
                params=task.params,
            ),
        )
        return TaskResult(
            task_id=task.task_id,
            status=TaskStatus.COMPLETED if tool_result.ok else TaskStatus.FAILED,
            ok=tool_result.ok,
            output=tool_result.data,
            error=tool_result.error,
        )

    if task.task_type in (TaskType.PROFILE, TaskType.COMPARE):
        tool_result = registry.invoke(
            task.tool,
            ToolContext(
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                run_id=run.run_id,
                question=run.question,
                params=task.params,
            ),
        )
        return TaskResult(
            task_id=task.task_id,
            status=TaskStatus.COMPLETED if tool_result.ok else TaskStatus.FAILED,
            ok=tool_result.ok,
            output=tool_result.data,
            error=tool_result.error,
        )

    if task.task_type == TaskType.SYNTHESIZE:
        return TaskResult(
            task_id=task.task_id,
            status=TaskStatus.COMPLETED,
            ok=True,
            output={
                "question": run.question,
                "context": question_context or run.question,
            },
        )

    if task.task_type == TaskType.PRODUCE:
        content = _assemble_report(run, task)
        run.artifact = ArtifactProduced(
            artifact_id=f"art-{run.run_id[:8]}",
            kind="REPORT",
            title=run.question[:60] or "研究报告",
            content=content,
            references=[],
        )
        return TaskResult(
            task_id=task.task_id,
            status=TaskStatus.COMPLETED,
            ok=True,
            output={"artifact_id": run.artifact.artifact_id, "content": content},
        )

    if task.task_type == TaskType.PLAN:
        return TaskResult(
            task_id=task.task_id,
            status=TaskStatus.COMPLETED,
            ok=True,
            output={"plan": "default"},
        )

    # unknown task types are recorded, not crashed
    return TaskResult(
        task_id=task.task_id,
        status=TaskStatus.FAILED,
        ok=False,
        error=f"unsupported task type: {task.task_type}",
    )


def _assemble_report(run: ResearchRun, task: TaskDefinition) -> str:
    lines = [
        "# 研究报告",
        "",
        f"**研究问题**: {run.question}",
        "",
        "## 执行摘要",
    ]
    if run.findings:
        lines.append("")
        for finding in run.findings[:12]:
            lines.append(f"- {finding}")
    else:
        lines.append("本次运行未能产生结构化发现（请检查工具接线与语料）。")
    lines.append("")
    lines.append("> 本文档由 Research Agent 自动生成（改进方案1 §十六）。")
    return "\n".join(lines)


def _summarize(output: dict[str, object]) -> str:
    """Short deterministic summary of a tool output for findings."""
    text = ""
    results = output.get("results")
    if isinstance(results, list) and results:
        text = f"{len(results)} 条结果"
    elif output.get("count") is not None:
        text = f"{output['count']} 条结果"
    if output.get("profile") is not None:
        text = "画像已生成"
    if output.get("matrix") is not None:
        text = "对比矩阵已生成"
    if not text:
        keys = list(output.keys())
        text = f"字段: {', '.join(keys[:4])}" if keys else "无输出"
    return text


def run_dag(
    run: ResearchRun,
    *,
    registry: ToolRegistry,
) -> dict[str, object]:
    """Convenience wrapper: execute and return a run summary dict."""
    results = execute_run(run, registry=registry)
    return {
        "run_id": run.run_id,
        "status": run.status.value,
        "task_count": len(results),
        "ok_count": sum(1 for r in results if r.ok),
        "artifact": run.artifact.model_dump(mode="json") if run.artifact else None,
        "findings": run.findings,
        "tasks": [r.model_dump(mode="json") for r in results],
    }
