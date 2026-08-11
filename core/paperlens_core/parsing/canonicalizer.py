"""Canonicalizer: turns ParseCandidates into CanonicalNodes (改进方案2 §17).

A candidate is "I think this is a paragraph"; the canonicalizer decides it is
*the* node, assigns a stable ``node_id``, derives ``revision_id`` from
content, and attaches provenance.
"""

from __future__ import annotations

import hashlib

from ..ir.canonical import CanonicalNode, NodeType
from ..ir.provenance import ProvenanceKind, ProvenanceRecord, hash_node_content
from .candidates import CandidateKind, ParseCandidate

_CANDIDATE_KIND_TO_NODE_TYPE = {
    CandidateKind.PARAGRAPH: NodeType.PARAGRAPH,
    CandidateKind.HEADING: NodeType.HEADING,
    CandidateKind.SECTION: NodeType.SECTION,
    CandidateKind.CAPTION: NodeType.CAPTION,
    CandidateKind.FIGURE: NodeType.FIGURE,
    CandidateKind.TABLE: NodeType.TABLE,
    CandidateKind.TABLE_CELL: NodeType.TABLE_ROW,
    CandidateKind.FORMULA: NodeType.FORMULA,
    CandidateKind.REFERENCE: NodeType.REFERENCE,
    CandidateKind.OTHER: NodeType.OTHER,
}


class Canonicalizer:
    """Deterministic candidate → CanonicalNode conversion."""

    def __init__(self, *, stable_node_ids: bool = True):
        self.stable_node_ids = stable_node_ids

    def canonize(
        self,
        candidate: ParseCandidate,
        *,
        source_version_id: str,
        order_index: int,
        parse_run_id: str = "",
        parent_id: str | None = None,
    ) -> CanonicalNode:
        node_type = _CANDIDATE_KIND_TO_NODE_TYPE.get(candidate.kind, NodeType.OTHER)

        content_hash = hash_node_content(
            candidate.text, page=candidate.page, bbox=candidate.bbox
        )

        if self.stable_node_ids and candidate.text:
            # node_id = hash of (kind + content) → stable across re-parses
            bbox = candidate.bbox or (0.0, 0.0, 0.0, 0.0)
            coarse_bbox = ",".join(str(round(float(value) / 8.0)) for value in bbox)
            logical_seed = hashlib.sha256(
                (
                    f"{source_version_id}::{node_type.value}::{candidate.page}::"
                    f"{coarse_bbox}::{candidate.text.strip()}"
                ).encode("utf-8")
            ).hexdigest()[:20]
            node_id = f"n-{logical_seed}"
        else:
            node_id = f"n-{candidate.candidate_id}"

        revision_id = f"r-{content_hash}"

        provenance = ProvenanceRecord(
            kind=ProvenanceKind.PARSER,
            backend=candidate.backend,
            backend_version=candidate.backend_version,
            parse_run_id=parse_run_id or candidate.parse_run_id,
            source_bbox=list(candidate.bbox) if candidate.bbox else None,
            page=candidate.page,
            confidence=candidate.confidence,
        )

        return CanonicalNode(
            node_id=node_id,
            revision_id=revision_id,
            source_version_id=source_version_id,
            node_type=node_type,
            parent_id=parent_id,
            order_index=order_index,
            page=candidate.page,
            bbox=candidate.bbox,
            text=candidate.text,
            content_hash=content_hash,
            semantic_hash=content_hash,
            confidence=candidate.confidence,
            provenance=[provenance],
            parse_run_ids=[parse_run_id or candidate.parse_run_id] if (parse_run_id or candidate.parse_run_id) else [],
            metadata=dict(candidate.raw_payload or {}),
        )
