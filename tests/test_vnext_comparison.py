"""Comparison v2 测试（改进方案1 §十 / 改进方案2 Phase F §32-38）。

验证：
- ComparabilityKey 规范化与可比性判定
- ResultRecord 从 PaperProfile 展平
- ResultAlignment 构建矩阵
- ComparisonSet 持久化模型与自定义维度
- GapAnalysis / ConsensusFinder
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from paperlens_core.comparison_v2.alignment import align_results
from paperlens_core.comparison_v2.comparability import (
    ComparabilityKey,
    ResultRecord,
    result_record_from_profile,
)
from paperlens_core.comparison_v2.models import ComparisonCell, ComparisonSet, CustomDimension
from paperlens_core.comparison_v2.synthesis import ConsensusFinder, GapAnalysis
from paperlens_core.papers.models import (
    ExperimentRecord,
    ExperimentResult,
    PaperProfile,
)


def _record(paper: str, dataset: str, metric: str, value: float) -> ResultRecord:
    return ResultRecord(
        paper_version_id=paper,
        paper_id=paper,
        key=ComparabilityKey(dataset=dataset, metric=metric),
        value=value,
        raw_text=f"{metric}: {value}",
    )


class TestComparability:
    def test_normalized_key_matches(self) -> None:
        a = ComparabilityKey(dataset="MS COCO", metric="mAP")
        b = ComparabilityKey(dataset="coco", metric="map")
        assert a.normalized() == b.normalized()

    def test_comparable_with(self) -> None:
        a = _record("p1", "COCO", "AP", 51.2)
        b = _record("p2", "coco", "ap", 47.8)
        assert a.comparable_with(b)

    def test_result_record_from_profile(self) -> None:
        profile = PaperProfile(
            paper_id="p1",
            paper_version_id="v1",
            title="T",
            experiments=[
                ExperimentRecord(
                    experiment_id="e1",
                    setup="COCO",
                    results=[
                        ExperimentResult(metric="AP", dataset="COCO", value=51.2),
                        ExperimentResult(metric="mAP", dataset="COCO", value=43.5),
                    ],
                )
            ],
        )
        records = result_record_from_profile(profile)
        assert len(records) == 2
        assert records[0].value == 51.2


class TestAlignment:
    def test_align_groups_same_key(self) -> None:
        records = [
            _record("p1", "COCO", "AP", 51.2),
            _record("p2", "coco", "ap", 47.8),
            _record("p1", "COCO", "FLOPs", 100.0),
        ]
        table = align_results(records)
        assert len(table.rows) == 2  # AP row + FLOPs row
        ap_row = next(r for r in table.rows if r.key.metric.lower() == "ap")
        assert len(ap_row.records) == 2
        assert set(table.columns()) == {"p1", "p2"}

    def test_align_row_filter(self) -> None:
        from paperlens_core.comparison_v2.alignment import align_results_row

        records = [_record("p1", "COCO", "AP", 1.0), _record("p1", "Cityscapes", "AP", 2.0)]
        filtered = align_results_row(records, dataset="coco")
        assert len(filtered) == 1


class TestComparisonSet:
    def test_set_model_roundtrip(self) -> None:
        comparison = ComparisonSet(
            comparison_id="cmp-1",
            workspace_id="ws-1",
            name="Detector comparison",
            question="Which detector is best on COCO?",
        )
        comparison.ensure_paper("p1", "v1")
        comparison.ensure_paper("p2", "v2")
        comparison.cells = [
            ComparisonCell(
                paper_version_id="v1",
                dimension="result_summary",
                value={"ap": 51.2},
            )
        ]
        data = comparison.model_dump(mode="json")
        restored = ComparisonSet.model_validate(data)
        assert restored.paper_ids == ["p1", "p2"]
        assert restored.cells[0].value == {"ap": 51.2}
        assert restored.status.value == "DRAFT"

    def test_gap_analysis(self) -> None:
        comparison = ComparisonSet(
            comparison_id="cmp-1",
            paper_version_ids=["v1", "v2", "v3"],
            dimensions=["result_summary"],
            cells=[
                ComparisonCell(paper_version_id="v1", dimension="result_summary", value={"ap": 1.0}),
                ComparisonCell(paper_version_id="v2", dimension="result_summary", value={"ap": 2.0}),
            ],
        )
        gaps = GapAnalysis().gaps(comparison)
        assert gaps and "result_summary" in gaps[0]

    def test_consensus_finder(self) -> None:
        comparison = ComparisonSet(
            comparison_id="cmp-1",
            paper_version_ids=["v1", "v2"],
            dimensions=["problem"],
            cells=[
                ComparisonCell(paper_version_id="v1", dimension="problem", value="occlusion"),
                ComparisonCell(paper_version_id="v2", dimension="problem", value="occlusion"),
            ],
        )
        consensus = ConsensusFinder().consensus(comparison)
        assert consensus and "problem" in consensus[0]

    def test_custom_dimensions_participate_in_gap_and_consensus(self) -> None:
        comparison = ComparisonSet(
            comparison_id="cmp-custom",
            paper_version_ids=["v1", "v2"],
            custom_dimensions=[CustomDimension(name="参数量", instruction="提取参数量")],
            cells=[
                ComparisonCell(paper_version_id="v1", dimension="参数量", value="25M"),
                ComparisonCell(paper_version_id="v2", dimension="参数量", value="25M"),
            ],
        )
        assert "参数量" in ConsensusFinder().consensus(comparison)[0]
        assert not any(gap.startswith("参数量:") for gap in GapAnalysis().gaps(comparison))
