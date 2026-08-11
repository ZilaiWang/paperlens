"""ParserBackend protocol and capability registry (改进方案2 §13).

A backend declares which document capabilities it can produce.  The planner
picks a backend per region based on ``DocumentProbe`` output; a candidate is
*never* trusted as final DocumentIR until the canonicalizer + fusion pass run.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class Capability(str, Enum):
    TEXT = "TEXT"                      # raw embedded text
    LAYOUT = "LAYOUT"                  # block geometry / columns / reading order
    GEOMETRY = "GEOMETRY"              # precise bbox geometry
    OCR = "OCR"                        # scanned page text extraction
    TABLE = "TABLE"                    # table detection + cell structure
    FORMULA = "FORMULA"                # math detection + latex
    FIGURE = "FIGURE"                  # figure bbox + caption linking
    BIBLIOGRAPHY = "BIBLIOGRAPHY"      # reference entry segmentation
    ACADEMIC_STRUCTURE = "ACADEMIC_STRUCTURE"  # sections/headings
    SEMANTIC = "SEMANTIC"              # title/authors/abstract extraction


class BackendProbe(BaseModel):
    """What one backend reports before doing the full parse."""

    model_config = ConfigDict(extra="allow")

    backend: str
    available: bool = True
    capabilities: set[Capability] = Field(default_factory=set)
    note: str = ""


class ParseRegion(str, Enum):
    """Regions of a document that may be handled by different backends."""

    FULL_DOCUMENT = "FULL_DOCUMENT"
    BODY_TEXT = "BODY_TEXT"
    TABLE = "TABLE"
    FORMULA = "FORMULA"
    FIGURE = "FIGURE"
    BIBLIOGRAPHY = "BIBLIOGRAPHY"
    METADATA = "METADATA"


class ParseRequest(BaseModel):
    """What the planner asks one backend to parse."""

    model_config = ConfigDict(extra="allow")

    document_path: str = ""
    raw_bytes: bytes | None = None
    region: ParseRegion = ParseRegion.FULL_DOCUMENT
    page_range: tuple[int, int] | None = None
    # planner-provided hints (columns, scanned, etc.)
    hints: dict[str, object] = Field(default_factory=dict)


class BackendResult(BaseModel):
    """Raw backend output.  Not yet DocumentIR."""

    model_config = ConfigDict(extra="allow")

    backend: str
    backend_version: str = ""
    region: ParseRegion = ParseRegion.FULL_DOCUMENT
    candidates: list["ParseCandidate"] = Field(default_factory=list)
    error: str = ""
    # per-page quality signals the fusion layer can use
    page_quality: dict[int, float] = Field(default_factory=dict)
    raw: dict[str, object] = Field(default_factory=dict)


@runtime_checkable
class ParserBackend(Protocol):
    """Uniform adapter interface every parser implements."""

    def capabilities(self) -> set[Capability]: ...

    def probe(self, document_path: str, raw_bytes: bytes | None = None) -> BackendProbe: ...

    def parse(self, request: ParseRequest) -> BackendResult: ...


# Circular-safe forward import for type checking.
from .candidates import ParseCandidate  # noqa: E402
