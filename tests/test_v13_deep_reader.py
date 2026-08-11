from __future__ import annotations

from paperlens_core.agents.adaptive import DepthRouter
from paperlens_core.agents.benchmark import AgentBenchCase, run_agent_bench
from paperlens_core.agents.models import AnalysisDepth
from paperlens_core.agents.planner import create_adaptive_run_plan
from paperlens_core.parsing.candidates import CandidateKind, ParseCandidate
from paperlens_core.parsing.contracts import BackendProbe, BackendResult, Capability
from paperlens_core.parsing.pipeline import ParsePipeline
from paperlens_core.parsing.planner import ParsePlanner
from paperlens_core.parsing.probe import ProbeReport
from paperlens_core.parsing.quality import QualityInspector
from paperlens_core.termbase.packs import TermPackCatalog


class FakeBackend:
    def __init__(self, name: str, *, repair: bool = False):
        self.name = name
        self.repair = repair
        self.calls: list[tuple[int, int] | None] = []

    def capabilities(self):
        capabilities = {Capability.TEXT, Capability.LAYOUT}
        if self.repair:
            capabilities.add(Capability.OCR)
        return capabilities

    def probe(self, document_path, raw_bytes=None):
        return BackendProbe(backend=self.name, available=True, capabilities=self.capabilities())

    def page_stats(self):
        return {1: {"text_chars": 10, "image_boxes": 1}}

    def parse(self, request):
        self.calls.append(request.page_range)
        if self.repair and request.page_range:
            text = "A repaired paragraph with sufficient detail and stable reading order. " * 10
            confidence = 0.98
        else:
            text = "x"
            confidence = 0.45
        return BackendResult(
            backend=self.name,
            candidates=[
                ParseCandidate(
                    candidate_id=f"{self.name}-{len(self.calls)}",
                    backend=self.name,
                    page=1,
                    kind=CandidateKind.PARAGRAPH,
                    text=text,
                    bbox=(10, 10, 500, 100),
                    confidence=confidence,
                )
            ],
        )


def test_pipeline_executes_targeted_repair_and_second_quality_pass():
    primary = FakeBackend("primary")
    repair = FakeBackend("paddleocr-vl", repair=True)
    result = ParsePipeline([primary, repair]).run(
        document_path="fake.pdf",
        raw_bytes=b"%PDF-fake",
        source_version_id="ver-test",
    )
    assert result.initial_quality is not None
    assert result.repair_passes >= 1
    assert (1, 1) in repair.calls
    assert result.quality.coverage_ratio > result.initial_quality.coverage_ratio
    assert any(target.repaired for target in result.repair_plan.targets)


def test_visual_backend_is_reserved_for_targeted_repair():
    primary = FakeBackend("primary")
    visual = FakeBackend("paddleocr-vl", repair=True)
    plan = ParsePlanner([primary, visual]).plan(
        ProbeReport(
            document_type="SCANNED",
            ocr_required=True,
            available_backends=["primary", "paddleocr-vl"],
        )
    )
    assert [step.backend for step in plan.steps] == ["primary"]


def test_quality_reports_pages_with_no_extracted_nodes():
    report = QualityInspector(page_count=2).inspect(
        ParsePipeline([FakeBackend("primary")]).run(
            document_path="fake.pdf",
            raw_bytes=b"%PDF-fake",
            source_version_id="ver-empty-page",
            max_repair_pages=0,
        ).document
    )
    assert report.page_quality[2] == "LOW"
    assert "LOW_TEXT_COVERAGE" in report.page_metrics[2].issues


def test_depth_router_and_adaptive_plan_are_bounded():
    assert DepthRouter().route("作者用了什么数据集？").depth == AnalysisDepth.QUICK
    routed = DepthRouter().route("请深入检查这篇论文是否能够复现")
    assert routed.depth == AnalysisDepth.DEEP
    run = create_adaptive_run_plan(
        run_id="run-v13",
        workspace_id="ws",
        project_id="",
        question="请深入检查这篇论文是否能够复现",
        scope_paper_ids=["paper"],
    )
    assert 3 <= len(run.tasks) <= 8
    assert len({task.task_id for task in run.tasks}) == len(run.tasks)
    assert any(task.capability == "reproduction.inspect" for task in run.tasks)


def test_agent_bench_and_term_pack_catalog():
    report = run_agent_bench([
        AgentBenchCase(question="作者用了什么数据集？", expected_depth=AnalysisDepth.QUICK),
        AgentBenchCase(question="请完整复现这篇论文", expected_depth=AnalysisDepth.DEEP, expected_intent="REPRODUCTION"),
    ])
    assert report.depth_accuracy == 1.0
    assert report.bounded_plan_ratio == 1.0
    catalog = TermPackCatalog()
    manifests = catalog.list()
    assert len(manifests) >= 4
    assert catalog.get("computer-vision-zh").manifest.term_count >= 8
