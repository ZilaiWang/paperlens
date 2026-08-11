"""Translation Memory (改进方案2 §23).

Strict exact-hash reuse for identical sources; fuzzy matches are returned
only as *context suggestions*, never auto-applied.
"""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, ConfigDict, Field

from ..utils import normalize_space


class MemoryHit(BaseModel):
    """One translation memory lookup result."""

    model_config = ConfigDict(extra="allow")

    source_hash: str
    translation: str
    exact: bool = False
    similarity: float = 0.0
    model: str = ""
    paper_id: str = ""
    project_id: str = ""
    quality_score: float = 0.0
    created_at: str = ""


class MemoryEntry(BaseModel):
    """A stored translation memory record (改进方案2 §23)."""

    model_config = ConfigDict(extra="allow")

    source_hash: str
    normalized_source: str
    translation: str
    language_pair: str = "en->zh"
    paper_id: str = ""
    project_id: str = ""
    model: str = ""
    context_snapshot: str = ""
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    created_at: str = ""


def hash_source(source: str) -> str:
    return hashlib.sha256(normalize_space(source).encode("utf-8")).hexdigest()[:24]


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[\w\u4e00-\u9fff]+", text.lower()))


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta and not tb:
        return 1.0
    union = ta | tb
    return len(ta & tb) / len(union)


class TranslationMemory:
    """In-process exact + fuzzy translation memory."""

    def __init__(self, entries: list[MemoryEntry] | None = None):
        self._exact: dict[str, MemoryEntry] = {}
        self._fuzzy: list[MemoryEntry] = []
        if entries:
            for entry in entries:
                self.add(entry)

    def add(self, entry: MemoryEntry) -> None:
        if not entry.translation or not entry.source_hash:
            return
        self._exact[entry.source_hash] = entry
        self._fuzzy.append(entry)

    def lookup(self, source: str, *, threshold: float = 0.65) -> MemoryHit | None:
        normalized = normalize_space(source)
        source_hash = hash_source(normalized)
        exact = self._exact.get(source_hash)
        if exact is not None:
            return MemoryHit(
                source_hash=source_hash,
                translation=exact.translation,
                exact=True,
                similarity=1.0,
                model=exact.model,
                paper_id=exact.paper_id,
                project_id=exact.project_id,
                quality_score=exact.quality_score,
                created_at=exact.created_at,
            )
        # fuzzy: only as context suggestion
        best: MemoryEntry | None = None
        best_similarity = 0.0
        for entry in self._fuzzy:
            similarity = _jaccard(normalized, entry.normalized_source)
            if similarity > best_similarity:
                best_similarity = similarity
                best = entry
        if best is not None and best_similarity >= threshold:
            return MemoryHit(
                source_hash=source_hash,
                translation=best.translation,
                exact=False,
                similarity=round(best_similarity, 3),
                model=best.model,
                paper_id=best.paper_id,
                project_id=best.project_id,
                quality_score=best.quality_score,
                created_at=best.created_at,
            )
        return None

    def size(self) -> int:
        return len(self._exact)


def memory_hit_kind(hit: MemoryHit | None) -> str:
    if hit is None:
        return "MISS"
    return "EXACT" if hit.exact else "FUZZY"
