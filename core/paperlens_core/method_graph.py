"""Method Navigator（改进方案3 §十·功能一，V4.4）。

把方法解析成证据绑定的有向图：Input → Backbone → 模块 → Loss → Inference →
Output。模型只输出严格结构（节点/边/证据），前端程序渲染。
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from .evidence import build_evidence_ledger
from .llm import StructuredModel
from .prompts import evidence_package
from .retrieval import BM25Index

METHOD_GRAPH_VERSION = "method-graph-v1"

METHOD_GRAPH_SYSTEM = """You extract the method pipeline of a CV paper as a
directed graph. Rules:
- node types: INPUT, BACKBONE, FEATURE, MODULE, LOSS, INFERENCE, OUTPUT.
- Every node must be supported by evidence from the package: cite 1-3
  evidence_ids per node. Never invent modules, names or equations.
- Edges connect the pipeline in execution order (source -> target).
- training_difference / inference_difference: describe how training and
  inference differ for this node when the paper states it; empty otherwise.
- Keep module names in English; value must be short and factual.""".strip()


class MethodNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    name: str
    node_type: str  # INPUT/BACKBONE/FEATURE/MODULE/LOSS/INFERENCE/OUTPUT
    description: str = ""
    evidence_ids: list[str] = Field(default_factory=list, max_length=3)
    training_difference: str = ""
    inference_difference: str = ""


class MethodEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    relation: str = "flows_into"


class MethodGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[MethodNode] = Field(default_factory=list, max_length=20)
    edges: list[MethodEdge] = Field(default_factory=list, max_length=30)


def build_method_graph(
    *,
    model: StructuredModel,
    chunks: list[object],
    paper_id: str,
    thread_id: str,
) -> MethodGraph:
    """BM25 检索方法相关段落 → 证据包 → LLM 结构化抽取 → 确定性过滤。"""
    index = BM25Index(chunks)  # type: ignore[arg-type]
    hits = index.search(
        "method pipeline architecture module backbone loss training inference",
        top_k=8,
        section_hints=["Method", "Approach", "Architecture", "Training", "Inference"],
    )
    ledger = build_evidence_ledger(f"method-{paper_id}", hits)
    known_ids = {item.evidence_id for item in ledger}
    package = evidence_package(
        [
            {
                "evidence_id": item.evidence_id,
                "page": item.page_start,
                "section": item.section_path,
                "text": item.verbatim_excerpt,
            }
            for item in ledger
        ]
    )
    user = "\n\n".join(
        [
            f"PAPER_ID: {paper_id}",
            package,
            "OUTPUT_SCHEMA:\n" + json.dumps(MethodGraph.model_json_schema(), ensure_ascii=False),
        ]
    )
    graph = model.invoke_json(
        system=METHOD_GRAPH_SYSTEM,
        user=user,
        schema=MethodGraph,
        stage="method_graph",
        thread_id=thread_id,
        temperature=0.0,
    )
    # 确定性过滤：未知证据 id 剔除；节点名去重保序
    seen: set[str] = set()
    clean_nodes: list[MethodNode] = []
    for node in graph.nodes:
        node.evidence_ids = [eid for eid in node.evidence_ids if eid in known_ids]
        key = node.name.strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        clean_nodes.append(node)
    graph.nodes = clean_nodes
    node_ids = {node.node_id for node in graph.nodes}
    graph.edges = [edge for edge in graph.edges if edge.source in node_ids and edge.target in node_ids]
    return graph
