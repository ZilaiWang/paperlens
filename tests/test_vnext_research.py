"""Research Workspace 测试（改进方案1 §十二-十四 / 改进方案2 Phase G §39-43）。

验证：
- Project / ResearchQuestion / Insight / Hypothesis 模型
- ResearchGraph 节点与边
- Artifact 模型
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from paperlens_core.research.artifacts import ArtifactKind, ResearchArtifact, artifact_from_text
from paperlens_core.research.graph import (
    ResearchEdge,
    ResearchEdgeType,
    ResearchGraph,
    ResearchNode,
    ResearchNodeType,
)
from paperlens_core.research.models import (
    Hypothesis,
    HypothesisStatus,
    Project,
    ResearchQuestion,
    ResearchQuestionStatus,
)


class TestProjectModels:
    def test_project_roundtrip(self) -> None:
        project = Project(
            project_id="prj-1",
            workspace_id="ws-1",
            name="Efficient detection survey",
            goal="Understand trade-offs of detection backbones.",
            paper_ids=["p1", "p2"],
        )
        data = project.model_dump(mode="json")
        restored = Project.model_validate(data)
        assert restored.paper_ids == ["p1", "p2"]
        assert restored.status.value == "ACTIVE"

    def test_question_lifecycle(self) -> None:
        question = ResearchQuestion(
            question_id="q1",
            project_id="prj-1",
            text="Which backbone is fastest?",
        )
        assert question.status == ResearchQuestionStatus.OPEN
        question.status = ResearchQuestionStatus.ANSWERED
        question.answer = "ResNet is fastest."
        data = question.model_dump(mode="json")
        restored = ResearchQuestion.model_validate(data)
        assert restored.status == ResearchQuestionStatus.ANSWERED

    def test_hypothesis_status(self) -> None:
        hypothesis = Hypothesis(
            hypothesis_id="h1",
            project_id="prj-1",
            statement="Feature alignment improves mAP by > 2 points.",
            status=HypothesisStatus.SUPPORTED,
        )
        assert hypothesis.status == HypothesisStatus.SUPPORTED


class TestResearchGraph:
    def _graph(self) -> ResearchGraph:
        graph = ResearchGraph(project_id="prj-1")
        graph.add_node(
            ResearchNode(
                node_id="n-q1",
                project_id="prj-1",
                node_type=ResearchNodeType.QUESTION,
                title="Which backbone?",
                ref_id="q1",
            )
        )
        graph.add_node(
            ResearchNode(
                node_id="n-p1",
                project_id="prj-1",
                node_type=ResearchNodeType.PAPER,
                title="Paper A",
                ref_id="p1",
            )
        )
        graph.add_node(
            ResearchNode(
                node_id="n-h1",
                project_id="prj-1",
                node_type=ResearchNodeType.HYPOTHESIS,
                title="Hypothesis",
                ref_id="h1",
            )
        )
        graph.add_edge(
            ResearchEdge(
                edge_id="e1",
                project_id="prj-1",
                source_id="n-p1",
                target_id="n-q1",
                edge_type=ResearchEdgeType.ADDRESSES,
            )
        )
        return graph

    def test_graph_add_and_neighbors(self) -> None:
        graph = self._graph()
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 1
        neighbors = graph.neighbors("n-q1")
        assert [n.node_id for n in neighbors] == ["n-p1"]

    def test_graph_nodes_of_type(self) -> None:
        graph = self._graph()
        papers = graph.nodes_of_type(ResearchNodeType.PAPER)
        assert len(papers) == 1

    def test_artifact_from_text(self) -> None:
        artifact = artifact_from_text(
            artifact_id="art-1",
            project_id="prj-1",
            title="Survey notes",
            content="collected",
            kind=ArtifactKind.NOTE,
        )
        assert isinstance(artifact, ResearchArtifact)
        assert artifact.kind == ArtifactKind.NOTE
