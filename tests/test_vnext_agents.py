"""Research Agent 测试（改进方案1 §十五-十六 / 改进方案2 Phase H §44-47）。

验证：
- create_run_plan 生成可执行 DAG
- TaskExecutor 拓扑执行 + 工具接线
- 失败工具不崩溃、DAG 推进
- PRODUCE 生成研究报告工件
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from paperlens_core.agents.executor import execute_run, run_dag
from paperlens_core.agents.models import RunStatus, TaskResult, TaskStatus
from paperlens_core.agents.planner import TaskPlanner, create_run_plan
from paperlens_core.agents.runtime import ToolContext, ToolRegistry, ToolResult, ToolSpec


def _registry_with_search(results: list[dict[str, object]]) -> ToolRegistry:
    registry = ToolRegistry()

    def search_handler(context: ToolContext) -> ToolResult:
        query = str(context.params.get("query", ""))
        return ToolResult(
            data={
                "query": query,
                "results": results,
                "count": len(results),
            }
        )

    registry.register(ToolSpec("search", "search", search_handler))

    def profile_handler(context: ToolContext) -> ToolResult:
        paper_ids = context.params.get("paper_ids", [])
        return ToolResult(data={"paper_ids": list(paper_ids), "profile": {"paper_id": paper_ids[0]}})

    registry.register(ToolSpec("profile", "profile", profile_handler))

    def compare_handler(context: ToolContext) -> ToolResult:
        paper_ids = context.params.get("paper_ids", [])
        return ToolResult(data={"paper_ids": list(paper_ids), "matrix": {}})

    registry.register(ToolSpec("compare", "compare", compare_handler))
    return registry


class TestPlanner:
    def test_create_run_plan_dag(self) -> None:
        run = create_run_plan(
            run_id="run-1",
            workspace_id="ws-1",
            project_id="prj-1",
            question="Which backbone is fastest?",
            scope_paper_ids=["p1", "p2"],
        )
        assert run.status == RunStatus.PLANNED
        task_types = [t.task_type.value for t in run.tasks]
        assert "RETRIEVE" in task_types
        assert "PRODUCE" in task_types
        # produce depends on synthesize
        produce = next(t for t in run.tasks if t.task_type.value == "PRODUCE")
        assert any(d.task_id == "t-synthesize" for d in produce.dependencies)


class TestExecutor:
    def test_full_dag_runs_to_artifact(self) -> None:
        run = create_run_plan(
            run_id="run-2",
            workspace_id="ws-1",
            project_id="prj-1",
            question="Compare detection backbones on COCO.",
            scope_paper_ids=["p1", "p2"],
        )
        registry = _registry_with_search(
            [{"unit_id": "u1", "text": "backbone result"}]
        )
        summary = run_dag(run, registry=registry)
        assert summary["status"] == "COMPLETED"
        assert summary["ok_count"] >= 3
        assert summary["artifact"] is not None
        assert "COCO" in summary["artifact"]["title"] or "Compare" in summary["artifact"]["title"]
        assert summary["findings"]
        assert summary["findings"][0] in summary["artifact"]["content"]

    def test_executor_results_record_status(self) -> None:
        run = create_run_plan(
            run_id="run-3",
            workspace_id="ws-1",
            project_id="prj-1",
            question="Q?",
            scope_paper_ids=["p1"],
        )
        registry = _registry_with_search([])
        results = execute_run(run, registry=registry)
        assert results
        assert all(isinstance(r, TaskResult) for r in results)
        completed = [r for r in results if r.status == TaskStatus.COMPLETED]
        assert completed

    def test_missing_tool_does_not_crash(self) -> None:
        run = create_run_plan(
            run_id="run-4",
            workspace_id="ws-1",
            project_id="prj-1",
            question="Q?",
            scope_paper_ids=[],
        )
        registry = ToolRegistry()  # no tools registered
        summary = run_dag(run, registry=registry)
        # 工具失败可以软降级，但不能再把没有真实工具产出的运行标成成功。
        assert summary["run_id"] == "run-4"
        assert summary["status"] == "FAILED"

    def test_planner_with_model_keeps_dag(self) -> None:
        planner = TaskPlanner(model=object())
        run = planner.plan(
            run_id="run-5",
            workspace_id="ws-1",
            project_id="prj-1",
            question="Q?",
            scope_paper_ids=[],
        )
        assert run.notes  # model planner annotated
        assert any(t.task_type.value == "PRODUCE" for t in run.tasks)


class TestResearchServiceCorpus:
    def test_production_chunk_page_start_is_used(self) -> None:
        from server.app.services.research import ResearchService

        class DocumentRepository:
            def load_document(self, version_id, kind):
                assert kind == "chunks"
                return [
                    {
                        "chunk_id": "c1",
                        "paper_version_id": version_id,
                        "section_path": "Methods",
                        "page_start": 7,
                        "page_end": 8,
                        "text": "A real stored chunk.",
                    }
                ]

        service = ResearchService(DocumentRepository(), object())
        units = service._corpus(["v1"])
        assert len(units) == 1
        assert units[0].page == 7
