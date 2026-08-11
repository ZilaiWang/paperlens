"""QualityInspector: per-node and per-document parse quality (改进方案1 §五).

Unlike the V1 page-level quality gate, this inspector scores the final
CanonicalDocument: node-level confidence aggregation, tiny-node ratio,
reading-order inversions, table/formula recovery, coverage.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..ir.canonical import CanonicalDocument, NodeType

GOOD = "GOOD"
SUSPECT = "SUSPECT"
LOW = "LOW"


class NodeQuality(BaseModel):
    model_config = ConfigDict(extra="allow")

    node_id: str
    page: int
    node_type: NodeType = NodeType.PARAGRAPH
    confidence: float = 0.0
    issues: list[str] = Field(default_factory=list)


class ParseQualityReport(BaseModel):
    model_config = ConfigDict(extra="allow")

    verdict: str = GOOD
    node_count: int = 0
    tiny_node_ratio: float = 0.0
    reading_order_inversions: int = 0
    table_node_count: int = 0
    formula_node_count: int = 0
    coverage_ratio: float = 0.0
    issues: list[str] = Field(default_factory=list)
    node_quality: list[NodeQuality] = Field(default_factory=list)
    page_quality: dict[int, str] = Field(default_factory=dict)


def _is_tiny(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    # fragment: fewer than ~6 words or ~14 chars and no digits
    word_count = len(stripped.split())
    return word_count < 4 and len(stripped) < 16


class QualityInspector:
    """Inspect a CanonicalDocument and produce a ParseQualityReport."""

    def __init__(self, *, page_width: float = 612.0, page_count: int | None = None):
        self.page_width = page_width
        self.page_count = page_count

    def inspect(self, document: CanonicalDocument) -> ParseQualityReport:
        nodes = document.nodes
        text_nodes = [n for n in nodes if n.node_type == NodeType.PARAGRAPH]
        tiny = [n for n in text_nodes if _is_tiny(n.text)]
        tiny_ratio = len(tiny) / max(1, len(text_nodes))

        inversions = 0
        page_quality: dict[int, str] = {}
        node_quality: list[NodeQuality] = []

        by_page: dict[int, list[object]] = {}
        for node in nodes:
            by_page.setdefault(node.page, []).append(node)

        for page in sorted(by_page):
            page_nodes = by_page[page]
            issues_page: list[str] = []
            # reading order: paragraph nodes should mostly descend in y0
            y0s = [
                (n.bbox[1] if n.bbox else None)
                for n in page_nodes
                if n.node_type == NodeType.PARAGRAPH and n.bbox
            ]
            inversions += _count_inversions(y0s)
            if len(page_nodes) >= 5 and tiny_ratio > 0.4:
                issues_page.append("TOO_MANY_TINY_BLOCKS")
            page_quality[page] = LOW if issues_page else GOOD
            for node in page_nodes:
                issues = list(issues_page)
                if node.node_type == NodeType.PARAGRAPH and _is_tiny(node.text):
                    issues.append("TINY_NODE")
                node_quality.append(
                    NodeQuality(
                        node_id=node.node_id,
                        page=node.page,
                        node_type=node.node_type,
                        confidence=node.confidence,
                        issues=issues,
                    )
                )

        table_count = sum(1 for n in nodes if n.node_type in (NodeType.TABLE, NodeType.TABLE_ROW))
        formula_count = sum(1 for n in nodes if n.node_type == NodeType.FORMULA)
        total_chars = sum(len(n.text) for n in nodes)
        page_count = self.page_count or (max((n.page for n in nodes), default=1))
        coverage_ratio = min(1.0, total_chars / max(1, page_count) / 2_200.0)

        issues: list[str] = []
        if tiny_ratio > 0.3:
            issues.append("TINY_NODE_RATIO_HIGH")
        if inversions > max(2, len(nodes) // 10):
            issues.append("READING_ORDER_UNCERTAIN")
        if coverage_ratio < 0.35:
            issues.append("LOW_COVERAGE")

        verdict = LOW if len(issues) >= 2 else SUSPECT if issues else GOOD

        return ParseQualityReport(
            verdict=verdict,
            node_count=len(nodes),
            tiny_node_ratio=round(tiny_ratio, 3),
            reading_order_inversions=inversions,
            table_node_count=table_count,
            formula_node_count=formula_count,
            coverage_ratio=round(coverage_ratio, 3),
            issues=issues,
            node_quality=node_quality,
            page_quality=page_quality,
        )


def _count_inversions(values: list[float | None]) -> int:
    cleaned = [v for v in values if v is not None]
    if len(cleaned) < 2:
        return 0
    inversions = 0
    for i in range(1, len(cleaned)):
        if cleaned[i] < cleaned[i - 1] - 1.0:  # 1pt tolerance
            inversions += 1
    return inversions
