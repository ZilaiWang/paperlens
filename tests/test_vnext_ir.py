"""DocumentIR vNext + Parser v2 数据模型与管线测试（改进方案1/2）。

验证：
- CanonicalNode 的 node_id/revision_id 拆分（方案2 §18）
- Provenance 记录（方案1 §三）
- Workspace 身份模型（方案2 §51-53）
- Parser v2 管线：probe → plan → parse → canonize → fuse → quality → repair
  （方案1 §三-五）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from paperlens_core.ir.canonical import CanonicalDocument, CanonicalNode, NodeType
from paperlens_core.ir.identity import Workspace, WorkspaceKind, is_owned
from paperlens_core.ir.provenance import ProvenanceKind, ProvenanceRecord, hash_node_content
from paperlens_core.ir.revisions import Revision, revision_from_node


def _block(block_id: str, text: str, page: int = 1, block_type: str = "TEXT"):
    return type(
        "Block",
        (),
        {
            "block_id": block_id,
            "paper_id": "p",
            "paper_version_id": "v",
            "page": page,
            "bbox": (50.0, 100.0, 450.0, 115.0),
            "block_type": block_type,
            "text": text,
            "content_sha256": "sha",
            "section_id": None,
            "metadata": {},
        },
    )()


class TestCanonicalNodeIdentity:
    def test_node_id_and_revision_id_are_separate(self) -> None:
        # 方案2 §18：node_id 逻辑身份，revision_id 内容身份
        node = CanonicalNode(
            node_id="node-387",
            revision_id="revision-2",
            source_version_id="ver-abc",
            node_type=NodeType.PARAGRAPH,
            page=1,
            bbox=(50.0, 100.0, 450.0, 115.0),
            text="We freeze the backbone.",
            content_hash="h1",
            confidence=0.95,
        )
        assert node.node_id != node.revision_id
        assert node.node_id == "node-387"

    def test_content_hash_tracks_text_and_location(self) -> None:
        h1 = hash_node_content("same text", page=1, bbox=(0, 0, 10, 10))
        h2 = hash_node_content("same text", page=1, bbox=(0, 0, 10, 10))
        h3 = hash_node_content("same text", page=2, bbox=(0, 0, 10, 10))
        assert h1 == h2
        assert h1 != h3

    def test_revision_from_node(self) -> None:
        node = CanonicalNode(
            node_id="n-1",
            revision_id="r-1",
            source_version_id="v",
            content_hash="ch",
            confidence=0.9,
        )
        revision = revision_from_node(node, created_at="2026-08-09T00:00:00Z")
        assert isinstance(revision, Revision)
        assert revision.node_id == "n-1"
        assert revision.content_hash == "ch"

    def test_provenance_record_roundtrip(self) -> None:
        provenance = ProvenanceRecord(
            kind=ProvenanceKind.FUSION,
            backend="docling",
            parse_run_id="pr-1",
            source_bbox=[0.0, 0.0, 100.0, 100.0],
            confidence=0.94,
        )
        data = provenance.model_dump(mode="json")
        restored = ProvenanceRecord.model_validate(data)
        assert restored.kind == ProvenanceKind.FUSION
        assert restored.backend == "docling"


class TestWorkspaceIdentity:
    def test_anonymous_workspace(self) -> None:
        ws = Workspace.anonymous()
        assert ws.workspace_id.startswith("ws-")
        assert ws.session_secret
        assert ws.kind == WorkspaceKind.PERSONAL

    def test_ownership_guard(self) -> None:
        assert is_owned("ws-a", "ws-a")
        assert not is_owned("ws-a", "ws-b")
        assert not is_owned("", "ws-b")


class TestParsePipeline:
    def _sample_blocks(self):
        """A 3-block born-digital style document (fragments)."""
        return [
            _block("b0", "the quick brown fox jumps over the lazy dog", 1),
            _block("b1", "second paragraph with enough words to read.", 1),
            _block("b2", "third paragraph also long enough to be useful.", 2),
        ]

    def test_canonical_document_from_blocks(self) -> None:
        from paperlens_core.ir.canonical import canonical_document_from_blocks

        doc = canonical_document_from_blocks(
            document_id="d",
            source_version_id="v",
            blocks=self._sample_blocks(),
            parse_run_id="pr-1",
        )
        assert isinstance(doc, CanonicalDocument)
        assert len(doc.nodes) == 3
        for node in doc.nodes:
            assert node.source_version_id == "v"
            assert node.parse_run_ids == ["pr-1"]
            assert node.provenance  # 每个节点都带 provenance

    def test_pipeline_runs_with_fake_backends(self) -> None:
        """用两个"候选后端"跑完整管线，验证 region fusion 选择更优者。"""
        from paperlens_core.parsing.candidates import CandidateKind, ParseCandidate
        from paperlens_core.parsing.contracts import (
            BackendProbe,
            BackendResult,
            Capability,
            ParseRequest,
        )
        from paperlens_core.parsing.pipeline import ParsePipeline

        class FakeBackendA:
            name = "a"

            def capabilities(self):
                return {Capability.TEXT, Capability.LAYOUT}

            def probe(self, document_path, raw_bytes=None):
                return BackendProbe(backend="a", capabilities=self.capabilities())

            def parse(self, request: ParseRequest) -> BackendResult:
                # 碎片化候选：片段多、文本短
                candidates = []
                for i in range(6):
                    candidates.append(
                        ParseCandidate(
                            candidate_id=f"a-{i}",
                            backend="a",
                            page=1,
                            kind=CandidateKind.PARAGRAPH,
                            text=f"Frag {i}",
                            confidence=0.5,
                        )
                    )
                return BackendResult(backend="a", region=request.region, candidates=candidates)

        class FakeBackendB:
            name = "b"

            def capabilities(self):
                return {Capability.TEXT, Capability.LAYOUT, Capability.TABLE}

            def probe(self, document_path, raw_bytes=None):
                return BackendProbe(backend="b", capabilities=self.capabilities())

            def parse(self, request: ParseRequest) -> BackendResult:
                candidates = [
                    ParseCandidate(
                        candidate_id="b-0",
                        backend="b",
                        page=1,
                        kind=CandidateKind.PARAGRAPH,
                        text="A complete paragraph with several words to read.",
                        bbox=(50.0, 100.0, 450.0, 115.0),
                        confidence=0.9,
                    )
                ]
                return BackendResult(backend="b", region=request.region, candidates=candidates)

        pipeline = ParsePipeline([FakeBackendA(), FakeBackendB()])
        result = pipeline.run(
            document_path="fake.pdf",
            raw_bytes=b"%PDF-1.4 fake",
            source_version_id="ver-1",
        )
        assert result.probe.page_count >= 1
        assert result.document.source_version_id == "ver-1"
        assert result.quality.node_count >= 1
        # 区域融合应保留不同区域，同时在页面级评分中选择更完整的 b。
        # 旧实现把整页文本压成一个 region，真实论文会因此每页只剩一个段落。
        assert result.fusion.chosen_pages[1] == "b"
        assert "b" in result.fusion.chosen_backends.values()
        texts = [node.text for node in result.document.nodes]
        assert any("complete paragraph" in text for text in texts)
        assert any("Frag" in text for text in texts)

    def test_quality_flags_tiny_nodes(self) -> None:
        from paperlens_core.parsing.candidates import CandidateKind, ParseCandidate
        from paperlens_core.parsing.canonicalizer import Canonicalizer
        from paperlens_core.parsing.quality import QualityInspector

        canonicalizer = Canonicalizer()
        nodes = []
        for i, text in enumerate(["M", "V", "C", "n", "a real paragraph with words."]):
            candidate = ParseCandidate(
                candidate_id=f"q-{i}",
                backend="a",
                page=1,
                kind=CandidateKind.PARAGRAPH,
                text=text,
                confidence=0.8,
            )
            nodes.append(canonicalizer.canonize(candidate, source_version_id="v", order_index=i))
        doc = CanonicalDocument(document_id="d", source_version_id="v", nodes=nodes)
        report = QualityInspector().inspect(doc)
        assert report.tiny_node_ratio > 0.5
        assert "TINY_NODE_RATIO_HIGH" in report.issues

    def test_repair_planner_targets_low_pages(self) -> None:
        from paperlens_core.parsing.quality import ParseQualityReport
        from paperlens_core.parsing.repair import RepairPlanner

        report = ParseQualityReport(
            verdict="LOW",
            page_quality={1: "LOW", 2: "GOOD", 3: "LOW"},
        )
        plan = RepairPlanner(["pymupdf", "pdfplumber"]).plan(
            report, primary_backend="pymupdf"
        )
        assert [t.page for t in plan.targets] == [1, 3]
        assert all(t.alternative_backend == "pdfplumber" for t in plan.targets)
