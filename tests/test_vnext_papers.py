"""Paper Intelligence 测试（改进方案1 §二十二-二十四 / 改进方案2 Phase E）。

验证：
- Hybrid Retrieval: RRF 融合 lexical + dense + section prior
- PaperProfile 离线构建（问题/方法/实验抽取）
- LLM 增强构建（StaticJSONModel 离线）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from paperlens_core.retrieval.hybrid import HybridRetriever, rank_fusion
from paperlens_core.retrieval.lexical import LexicalIndex, TextUnit


def _corpus() -> list[TextUnit]:
    units = [
        TextUnit(
            unit_id="u1",
            paper_version_id="p1",
            text="We propose a backbone that freezes weights during fine-tuning.",
            section_path="Method",
            page=3,
        ),
        TextUnit(
            unit_id="u2",
            paper_version_id="p1",
            text="Object detection requires region proposal networks.",
            section_path="Introduction",
            page=1,
        ),
        TextUnit(
            unit_id="u3",
            paper_version_id="p2",
            text="Fine-tuning the backbone improves few-shot accuracy.",
            section_path="Method",
            page=2,
        ),
        TextUnit(
            unit_id="u4",
            paper_version_id="p2",
            text="Ground truth labels come from the annotation pipeline.",
            section_path="Data",
            page=4,
        ),
    ]
    return units


class TestHybridRetrieval:
    def test_lexical_index_bm25(self) -> None:
        index = LexicalIndex().build(_corpus())
        hits = index.search("backbone fine-tuning", top_k=3)
        assert hits
        ids = [unit_id for unit_id, _ in hits]
        # u1 and u3 mention backbone + fine-tuning
        assert "u1" in ids
        assert "u3" in ids

    def test_rrf_fusion(self) -> None:
        fused = rank_fusion([["a", "b", "c"], ["c", "a"]], top_k=3)
        assert fused[0] in ("a", "c")

    def test_hybrid_combines_sources(self) -> None:
        index = LexicalIndex().build(_corpus())
        # dense retriever favors u2; lexical favors u1/u3
        retriever = HybridRetriever(
            index,
            dense_retriever=lambda query: ["u2", "u4"],
            section_prior=lambda section: ["u3", "u1"],
        )
        results = retriever.search("backbone", section_query="Method")
        assert results
        ids = [r.unit.unit_id for r in results]
        # u3 is boosted by section prior + lexical
        assert "u3" in ids
        for result in results:
            assert result.sources  # every result records its sources

    def test_hybrid_without_dense_still_works(self) -> None:
        index = LexicalIndex().build(_corpus())
        retriever = HybridRetriever(index)
        results = retriever.search("object detection")
        assert results
        assert results[0].unit.unit_id == "u2"


class TestPaperProfileOffline:
    def _blocks(self):
        """Simulate a parsed paper with headings and paragraphs."""
        def block(block_type: str, text: str, page: int = 1):
            return type(
                "Block",
                (),
                {
                    "block_id": "b",
                    "paper_id": "p",
                    "paper_version_id": "v1",
                    "page": page,
                    "bbox": (0.0, 0.0, 100.0, 100.0),
                    "block_type": block_type,
                    "text": text,
                    "content_sha256": "sha",
                    "section_id": None,
                    "metadata": {},
                },
            )()

        return [
            block("HEADING", "Abstract"),
            block("TEXT", "We introduce an efficient detector for autonomous driving."),
            block("HEADING", "Introduction"),
            block("TEXT", "Object detection is crucial but challenging in crowded scenes."),
            block("HEADING", "Method"),
            block("TEXT", "We propose a lightweight backbone with feature alignment."),
            block("HEADING", "Experiments"),
            block("TEXT", "On COCO, our AP: 51.2 and mAP: 43.5. On Cityscapes, AP: 47.8."),
        ]

    def test_offline_profile_extracts_problem_method_experiments(self) -> None:
        from paperlens_core.papers.profile_builder import PaperProfileBuilder

        builder = PaperProfileBuilder()
        profile = builder.build_offline(
            paper_id="p1",
            paper_version_id="v1",
            title="Efficient Detector",
            sections={
                "Abstract": "We introduce an efficient detector for autonomous driving.",
                "Introduction": "Object detection is crucial but challenging in crowded scenes.",
                "Method": "We propose a lightweight backbone with feature alignment.",
                "Experiments": "On COCO, our AP: 51.2 and mAP: 43.5.",
            },
            built_at="2026-08-11T00:00:00Z",
        )
        assert profile.problem.problem  # problem extracted
        assert profile.method  # method blocks extracted
        assert profile.experiments  # result rows extracted
        assert profile.experiments[0].results
        assert profile.experiments[0].results[0].value is not None
        assert profile.title == "Efficient Detector"
        assert "目标检测" in profile.domain

    def test_profile_built_from_blocks(self) -> None:
        from paperlens_core.papers.profile_builder import PaperProfileBuilder

        builder = PaperProfileBuilder()
        profile = builder.build_offline(
            paper_id="p1",
            paper_version_id="v1",
            title="Efficient Detector",
            blocks=self._blocks(),
        )
        assert "Method" in [m.name for m in profile.method] or profile.method
        assert profile.experiments

    def test_profile_with_model_enrichment(self) -> None:
        from paperlens_core.llm import StaticJSONModel
        from paperlens_core.papers.profile_builder import PaperProfileBuilder

        model = StaticJSONModel(
            [
                {
                    "problem": {
                        "problem": "Crowded scene detection is hard.",
                        "motivation": "Autonomous driving needs it.",
                        "challenges": ["occlusion", "small objects"],
                    },
                    "method": [
                        {
                            "name": "Feature Alignment",
                            "role": "feature extractor",
                            "summary": "Aligns multi-scale features.",
                        }
                    ],
                    "experiments": [
                        {
                            "experiment_id": "e1",
                            "setup": "COCO",
                            "results": [
                                {"metric": "AP", "dataset": "COCO", "value": 51.2}
                            ],
                        }
                    ],
                }
            ]
        )
        builder = PaperProfileBuilder(model=model)
        profile = builder.build_with_model(
            paper_id="p1",
            paper_version_id="v1",
            title="Efficient Detector",
            abstract="We introduce an efficient detector.",
            sections={
                "Introduction": "Object detection is crucial but challenging.",
                "Method": "We propose feature alignment.",
                "Experiments": "AP 51.2.",
            },
            thread_id="t-profile",
        )
        assert profile.status == "COMPLETE"
        assert profile.problem.challenges  # LLM extracted
        assert profile.method[0].name == "Feature Alignment"
        assert profile.experiments[0].results[0].value == 51.2
