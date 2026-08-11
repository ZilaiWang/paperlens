"""Provenance: every node remembers where it came from.

改进方案1 §三（Parser v2 provenance） / §四（DocumentIR vNext provenance）。

A ``ProvenanceRecord`` answers: which backend produced this node, in which
parse run, with which confidence, and where on the page the source lived.
Downstream services (translation, comparison, research) can therefore always
trace a claim back to a concrete parser decision instead of trusting a magic
``text`` field.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProvenanceKind(str, Enum):
    """What kind of decision produced the content."""

    CANONICALIZER = "CANONICALIZER"  # deterministic conversion of a candidate
    PARSER = "PARSER"                # direct backend output
    FUSION = "FUSION"                # region-level fusion picked this backend
    REPAIR = "REPAIR"                # repair planner re-ran a page/region
    TRANSLATION = "TRANSLATION"      # translation engine produced this
    EXTRACTION = "EXTRACTION"        # structured extraction (table/profile)
    MANUAL = "MANUAL"                # user corrected / overrode


class ProvenanceRecord(BaseModel):
    """One provenance entry attached to a CanonicalNode or derived object."""

    model_config = ConfigDict(extra="allow")

    kind: ProvenanceKind = ProvenanceKind.CANONICALIZER
    backend: str = ""
    backend_version: str = ""
    parse_run_id: str = ""
    source_bbox: list[float] | None = None
    page: int | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    note: str = ""


def hash_node_content(text: str, *, page: int | None = None, bbox: Any = None) -> str:
    """Content hash for revision binding.

    The hash covers text plus the coarse location (page, bbox) so that a
    paragraph moved to a different page by a different parser is still seen as
    a *revision* of the same node rather than silently overwritten.
    """
    location = ""
    if page is not None:
        location += str(page)
    if bbox:
        location += "|" + ",".join(str(round(float(v), 2)) for v in bbox)
    payload = f"{location}::{text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
