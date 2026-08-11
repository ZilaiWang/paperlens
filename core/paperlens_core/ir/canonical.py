"""Canonical document model: node identity separated from revision content.

改进方案1 §四 / 改进方案2 §17-18:

    SourceVersion
        └── ParseRun
                └── CanonicalDocument
                        └── CanonicalNode
                                ├── revision_id
                                └── provenance[]

``node_id`` is the *logical* identity of "the same paragraph" across parses
(annotations bind here).  ``revision_id`` identifies one concrete parse of
that node (translation caches bind here via ``content_hash``).
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .provenance import ProvenanceRecord


class NodeType(str, Enum):
    DOCUMENT = "DOCUMENT"
    SECTION = "SECTION"
    HEADING = "HEADING"
    PARAGRAPH = "PARAGRAPH"
    FIGURE = "FIGURE"
    CAPTION = "CAPTION"
    TABLE = "TABLE"
    TABLE_ROW = "TABLE_ROW"
    FORMULA = "FORMULA"
    REFERENCE = "REFERENCE"
    FOOTNOTE = "FOOTNOTE"
    OTHER = "OTHER"


class CanonicalNode(BaseModel):
    """One logical unit of a parsed document.

    ``node_id`` stays stable for the same logical content across re-parses;
    ``revision_id`` changes whenever the parsed content of this node changes.
    """

    model_config = ConfigDict(extra="allow")

    node_id: str
    revision_id: str
    source_version_id: str
    node_type: NodeType = NodeType.PARAGRAPH

    parent_id: str | None = None
    order_index: int = 0

    page: int = 1
    bbox: tuple[float, float, float, float] | None = None

    text: str = ""
    content_hash: str = ""
    semantic_hash: str = ""

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    parse_run_ids: list[str] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)

    # optional carry-over from V1 adapters
    block_id: str = ""
    section_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalDocument(BaseModel):
    """The full parsed document as a tree of CanonicalNodes."""

    model_config = ConfigDict(extra="allow")

    document_id: str
    source_version_id: str
    parse_run_ids: list[str] = Field(default_factory=list)
    root: CanonicalNode | None = None
    nodes: list[CanonicalNode] = Field(default_factory=list)

    def node(self, node_id: str) -> CanonicalNode | None:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None

    def children(self, parent_id: str | None) -> list[CanonicalNode]:
        return [
            node
            for node in self.nodes
            if (node.parent_id or None) == parent_id
        ]


def canonical_node_from_block(
    *,
    node_id: str,
    revision_id: str,
    source_version_id: str,
    block: Any,
    node_type: NodeType | None = None,
    content_hash: str = "",
    semantic_hash: str = "",
    confidence: float = 1.0,
    parse_run_id: str = "",
    provenance_kind: str = "CANONICALIZER",
    backend: str = "v1-adapter",
    supersedes: list[str] | None = None,
) -> CanonicalNode:
    """Build a CanonicalNode from a V1 ``documents.Block`` (compatibility shim).

    The V1 block carries ``block_id`` (parse-scoped index identity in some
    legacy parsers).  We keep it in ``metadata`` and give the canonical node
    its own stable ``node_id`` + ``revision_id`` pair, so downstream services
    (translation cache, annotations) never depend on parser-internal ids.
    """
    text = getattr(block, "text", "") or ""
    bbox = getattr(block, "bbox", None)
    page = getattr(block, "page", 1) or 1
    block_type = str(getattr(block, "block_type", "") or "TEXT")

    resolved_type = node_type or _node_type_from_block(block_type)

    if not content_hash:
        from .provenance import hash_node_content

        content_hash = hash_node_content(text, page=page, bbox=bbox)
    if not semantic_hash:
        semantic_hash = content_hash

    provenance = [
        ProvenanceRecord(
            kind=provenance_kind,
            backend=backend,
            parse_run_id=parse_run_id,
            source_bbox=list(bbox) if bbox else None,
            page=page,
            confidence=confidence,
        )
    ]

    return CanonicalNode(
        node_id=node_id,
        revision_id=revision_id,
        source_version_id=source_version_id,
        node_type=resolved_type,
        page=page,
        bbox=bbox,
        text=text,
        content_hash=content_hash,
        semantic_hash=semantic_hash,
        confidence=confidence,
        provenance=provenance,
        parse_run_ids=[parse_run_id] if parse_run_id else [],
        block_id=getattr(block, "block_id", "") or "",
        section_id=getattr(block, "section_id", None),
        metadata=dict(getattr(block, "metadata", {}) or {}),
    )


def _node_type_from_block(block_type: str) -> NodeType:
    mapping = {
        "TEXT": NodeType.PARAGRAPH,
        "HEADING": NodeType.HEADING,
        "CAPTION": NodeType.CAPTION,
        "FORMULA": NodeType.FORMULA,
        "TABLE_ROW": NodeType.TABLE_ROW,
        "REFERENCE_ENTRY": NodeType.REFERENCE,
        "FIGURE": NodeType.FIGURE,
        "TABLE": NodeType.TABLE,
        "UNKNOWN_MEDIA": NodeType.OTHER,
    }
    return mapping.get(block_type, NodeType.OTHER)


def canonical_document_from_blocks(
    *,
    document_id: str,
    source_version_id: str,
    blocks: list[Any],
    parse_run_id: str = "",
    backend: str = "v1-adapter",
    confidence: float = 1.0,
) -> CanonicalDocument:
    """Build a CanonicalDocument from a flat V1 block list.

    Parent-child relationships are preserved from V1 ``section_id`` when
    available; otherwise nodes are flattened with their page order.
    """
    from .provenance import hash_node_content

    nodes: list[CanonicalNode] = []
    section_nodes: dict[str, CanonicalNode] = {}

    def stable_identity(block: Any, prefix: str = "n") -> str:
        bbox = getattr(block, "bbox", None) or (0.0, 0.0, 0.0, 0.0)
        coarse_bbox = ",".join(str(round(float(value) / 8.0)) for value in bbox)
        seed = (
            f"{source_version_id}::{getattr(block, 'block_type', '')}::"
            f"{getattr(block, 'page', 1)}::{coarse_bbox}::"
            f"{(getattr(block, 'text', '') or '').strip()}"
        )
        return f"{prefix}-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:20]}"

    for block in blocks:
        block_type = str(getattr(block, "block_type", "") or "TEXT")
        section_id = getattr(block, "section_id", None)

        if block_type == "HEADING" and section_id:
            section_node = canonical_node_from_block(
                node_id=stable_identity(block, "sec"),
                revision_id=f"r-{hash_node_content(getattr(block, 'text', '') or '', page=getattr(block, 'page', 1), bbox=getattr(block, 'bbox', None))}",
                source_version_id=source_version_id,
                block=block,
                node_type=NodeType.SECTION,
                content_hash=hash_node_content(
                    getattr(block, "text", "") or "",
                    page=getattr(block, "page", 1) or 1,
                    bbox=getattr(block, "bbox", None),
                ),
                parse_run_id=parse_run_id,
                backend=backend,
                confidence=confidence,
            )
            section_nodes[section_id] = section_node
            nodes.append(section_node)

        node = canonical_node_from_block(
            node_id=stable_identity(block),
            revision_id=f"r-{hash_node_content(getattr(block, 'text', '') or '', page=getattr(block, 'page', 1), bbox=getattr(block, 'bbox', None))}",
            source_version_id=source_version_id,
            block=block,
            parse_run_id=parse_run_id,
            backend=backend,
            confidence=confidence,
        )
        if section_id and section_id in section_nodes:
            node.parent_id = section_nodes[section_id].node_id
        nodes.append(node)

    return CanonicalDocument(
        document_id=document_id,
        source_version_id=source_version_id,
        parse_run_ids=[parse_run_id] if parse_run_id else [],
        nodes=nodes,
    )
