"""TermEntry model (改进方案1 §六 / 改进方案2 §22)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TermScope(str, Enum):
    SYSTEM = "SYSTEM"
    DOMAIN = "DOMAIN"
    PROJECT = "PROJECT"
    PAPER = "PAPER"
    USER = "USER"


class TermPolicy(str, Enum):
    TRANSLATE = "TRANSLATE"
    KEEP = "KEEP"              # keep English (e.g. "Grounding DINO")
    CONTEXTUAL = "CONTEXTUAL"  # decide per sentence


class TermEntry(BaseModel):
    """A term with domain context, policy and lock state."""

    model_config = ConfigDict(extra="allow")

    source: str
    target: str = ""
    language_pair: str = "en->zh"

    sense: str = ""        # "region proposal"
    domain: str = ""       # "object_detection"

    scope: TermScope = TermScope.SYSTEM

    policy: TermPolicy = TermPolicy.TRANSLATE

    locked: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    source_evidence: list[str] = Field(default_factory=list)  # paper ids / refs
    examples: list[str] = Field(default_factory=list)         # sentence pairs

    aliases: list[str] = Field(default_factory=list)
    allowed_translations: list[str] = Field(default_factory=list)
    deprecated_translations: list[str] = Field(default_factory=list)
    keep_english: bool = False  # shorthand for policy=KEEP

    updated_at: str = ""

    @property
    def effective_policy(self) -> TermPolicy:
        if self.keep_english:
            return TermPolicy.KEEP
        return self.policy


class TermEntryUpsert(BaseModel):
    """API-friendly upsert payload."""

    source: str = Field(min_length=1, max_length=200)
    target: str = Field(default="", max_length=500)
    domain: str = ""
    sense: str = ""
    policy: TermPolicy = TermPolicy.TRANSLATE
    scope: TermScope = TermScope.PROJECT
    locked: bool = False
    keep_english: bool = False
    aliases: list[str] = Field(default_factory=list, max_length=20)


class TermMatch(BaseModel):
    """Result of resolving one term occurrence."""

    source: str
    target: str
    scope: TermScope
    policy: TermPolicy
    confidence: float = 0.0
    locked: bool = False
    matched: bool = False


class TermPackManifest(BaseModel):
    """Installable, versioned terminology pack metadata."""

    pack_id: str
    name: str
    domain: str
    version: str = "1.0.0"
    description: str = ""
    language_pair: str = "en->zh"
    # Bundled starter packs are original PaperLens data and ship under the
    # repository license. External catalogs must declare their own license.
    license: str = "MIT"
    recommended: bool = False
    term_count: int = 0


class TermPack(BaseModel):
    manifest: TermPackManifest
    terms: list[TermEntry] = Field(default_factory=list)
