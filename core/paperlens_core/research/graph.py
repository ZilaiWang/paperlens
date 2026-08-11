"""ResearchGraph: the growing knowledge web (改进方案1 §十三 / 改进方案2 §40)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ResearchNodeType(str, Enum):
    QUESTION = "QUESTION"
    INSIGHT = "INSIGHT"
    HYPOTHESIS = "HYPOTHESIS"
    PAPER = "PAPER"
    COMPARISON = "COMPARISON"
    NOTE = "NOTE"
    EXPERIMENT = "EXPERIMENT"


class ResearchEdgeType(str, Enum):
    ADDRESSES = "ADDRESSES"          # paper -> question
    SUPPORTS = "SUPPORTS"            # insight -> hypothesis
    CONTRADICTS = "CONTRADICTS"      # insight -> hypothesis
    EXTENDS = "EXTENDS"              # question -> question
    INFORMS = "INFORMS"              # paper -> insight
    RELATES_TO = "RELATES_TO"        # generic


class ResearchNode(BaseModel):
    """One node in the research graph."""

    model_config = ConfigDict(extra="allow")

    node_id: str
    project_id: str
    node_type: ResearchNodeType = ResearchNodeType.NOTE
    title: str = ""
    content: str = ""
    ref_id: str = ""                 # id of the backing entity (question/hypothesis/...)
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: str = ""


class ResearchEdge(BaseModel):
    """A typed link between two research nodes."""

    model_config = ConfigDict(extra="allow")

    edge_id: str
    project_id: str
    source_id: str
    target_id: str
    edge_type: ResearchEdgeType = ResearchEdgeType.RELATES_TO
    note: str = ""
    created_at: str = ""


class ResearchGraph(BaseModel):
    """The full graph for one project."""

    model_config = ConfigDict(extra="allow")

    project_id: str
    nodes: list[ResearchNode] = Field(default_factory=list)
    edges: list[ResearchEdge] = Field(default_factory=list)

    def add_node(self, node: ResearchNode) -> None:
        if not any(n.node_id == node.node_id for n in self.nodes):
            self.nodes.append(node)

    def add_edge(self, edge: ResearchEdge) -> None:
        if not any(e.edge_id == edge.edge_id for e in self.edges):
            self.edges.append(edge)

    def neighbors(self, node_id: str) -> list[ResearchNode]:
        ids = {
            e.source_id for e in self.edges if e.target_id == node_id
        } | {
            e.target_id for e in self.edges if e.source_id == node_id
        }
        return [n for n in self.nodes if n.node_id in ids]

    def nodes_of_type(self, node_type: ResearchNodeType) -> list[ResearchNode]:
        return [n for n in self.nodes if n.node_type == node_type]
