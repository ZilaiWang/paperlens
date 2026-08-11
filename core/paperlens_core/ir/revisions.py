"""Revision tracking for canonical nodes.

改进方案2 §18: node_id vs revision_id.

``node_id`` is the logical identity ("the same paragraph").
``revision_id`` is one concrete parse of that node.  A re-parse that changes
the content of the node must produce a *new* revision; annotations bound to
``node_id`` survive, while translation caches bound to ``revision_id`` /
``content_hash`` are correctly invalidated.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RevisionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class Revision(BaseModel):
    """One concrete content snapshot of a canonical node."""

    model_config = ConfigDict(extra="allow")

    revision_id: str
    node_id: str
    source_version_id: str
    content_hash: str = ""
    status: RevisionStatus = RevisionStatus.ACTIVE
    # for the supersede chain: which revision this one replaces
    supersedes: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    parse_run_id: str = ""
    created_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


def revision_from_node(
    node: Any,
    *,
    revision_id: str | None = None,
    created_at: str = "",
    parse_run_id: str = "",
) -> Revision:
    """Build a Revision from a CanonicalNode (or V1 Block)."""
    node_id = getattr(node, "node_id", "")
    source_version_id = getattr(node, "source_version_id", "")
    content_hash = getattr(node, "content_hash", "") or getattr(node, "content_sha256", "")
    confidence = getattr(node, "confidence", 1.0)
    return Revision(
        revision_id=revision_id or getattr(node, "revision_id", "") or f"rev-{content_hash[:12]}",
        node_id=node_id or getattr(node, "block_id", ""),
        source_version_id=source_version_id,
        content_hash=content_hash,
        confidence=confidence,
        parse_run_id=parse_run_id or getattr(node, "parse_run_id", ""),
        created_at=created_at,
    )
