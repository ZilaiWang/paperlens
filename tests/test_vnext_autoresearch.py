"""AutoResearch Bridge 测试（改进方案1 §二十六 / 改进方案2 Phase I §48-50）。

验证：
- ResearchContextPack 构建与往返
- pack_from_project（duck typing）
- ExperimentRun 记录与 ResultAnalysis
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from paperlens_core.autoresearch.context import (
    PaperContext,
    ResearchContextPack,
    build_research_context_pack,
    pack_from_project,
)
from paperlens_core.autoresearch.experiment import (
    ExperimentPlan,
    ResultAnalysis,
    RunKind,
    analyze_run_results,
    create_experiment_run,
)


class TestContextPack:
    def test_build_and_roundtrip(self) -> None:
        pack = build_research_context_pack(
            pack_id="pack-1",
            workspace_id="ws-1",
            project_id="prj-1",
            project_name="Detector survey",
            goal="Find fastest detector.",
            questions=["Which is fastest?"],
            hypotheses=[{"id": "h1", "statement": "A is fastest", "status": "PROPOSED"}],
            papers=[
                PaperContext(paper_id="p1", paper_version_id="v1", title="A")
            ],
        )
        data = pack.as_dict()
        restored = ResearchContextPack.model_validate(data)
        assert restored.pack_id == "pack-1"
        assert restored.hypotheses[0]["statement"] == "A is fastest"
        assert restored.papers[0].title == "A"

    def test_pack_from_project_ducktyping(self) -> None:
        class FakeProject:
            project_id = "prj-1"
            workspace_id = "ws-1"
            name = "Survey"
            goal = "Goal"

        class FakeQuestion:
            text = "Q1?"

        class FakeHypothesis:
            hypothesis_id = "h1"
            statement = "S1"
            status = type("S", (), {"value": "PROPOSED"})()

        pack = pack_from_project(
            project=FakeProject(),
            questions=[FakeQuestion()],
            hypotheses=[FakeHypothesis()],
        )
        assert pack.project_name == "Survey"
        assert pack.questions == ["Q1?"]
        assert pack.hypotheses[0]["status"] == "PROPOSED"


class TestExperimentRun:
    def test_create_and_analyze(self) -> None:
        run = create_experiment_run(
            run_id="run-1",
            workspace_id="ws-1",
            project_id="prj-1",
            plan=ExperimentPlan(
                run_id="run-1",
                kind=RunKind.SCRIPT,
                command="python eval.py",
                parameters={"dataset": "COCO"},
            ),
        )
        assert run.status.value == "PLANNED"
        run.status = run.status.COMPLETED
        analysis = analyze_run_results(
            run=run,
            verdict="SUPPORTED",
            summary="A is fastest.",
            key_metrics=[{"metric": "mAP", "value": 51.2}],
        )
        assert isinstance(analysis, ResultAnalysis)
        assert analysis.run_id == "run-1"
        assert analysis.verdict == "SUPPORTED"
        assert analysis.key_metrics[0]["metric"] == "mAP"
