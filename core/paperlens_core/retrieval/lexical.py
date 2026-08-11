"""Lexical retrieval baseline (BM25-style), re-usable across papers.

The V1 ``retrieval.py`` remains for in-paper QA; this module provides a
lightweight corpus-level lexical index used by HybridRetriever and by
Research/Comparison features that search across many papers.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class TextUnit(BaseModel):
    """One searchable unit (a chunk or paragraph) with provenance."""

    model_config = ConfigDict(extra="allow")

    unit_id: str
    paper_version_id: str
    text: str = ""
    section_path: str = ""
    page: int = 0
    metadata: dict[str, object] = Field(default_factory=dict)


@dataclass
class _Posting:
    df: int = 0
    tf: dict[str, int] = field(default_factory=dict)


class LexicalIndex:
    """Build a BM25 index over TextUnits."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.units: list[TextUnit] = []
        self._index: dict[str, _Posting] = {}
        self._avg_len: float = 0.0

    def add(self, unit: TextUnit) -> None:
        self.units.append(unit)
        seen: set[str] = set()
        for token in tokenize(unit.text):
            posting = self._index.setdefault(token, _Posting())
            posting.tf[unit.unit_id] = posting.tf.get(unit.unit_id, 0) + 1
            if token not in seen:
                posting.df += 1
                seen.add(token)

    def build(self, units: Iterable[TextUnit]) -> "LexicalIndex":
        for unit in units:
            self.add(unit)
        total_len = sum(len(tokenize(u.text)) for u in self.units)
        self._avg_len = total_len / max(1, len(self.units))
        return self

    def search(self, query: str, *, top_k: int = 8) -> list[tuple[str, float]]:
        query_tokens = tokenize(query)
        if not query_tokens or not self.units:
            return []
        n_docs = len(self.units)
        scores: dict[str, float] = {}
        doc_lens = {u.unit_id: len(tokenize(u.text)) for u in self.units}
        for token in query_tokens:
            posting = self._index.get(token)
            if posting is None:
                continue
            idf = math.log(1 + (n_docs - posting.df + 0.5) / (posting.df + 0.5))
            for unit_id, tf in posting.tf.items():
                dl = doc_lens.get(unit_id, 1)
                denom = tf + self.k1 * (1 - self.b + self.b * dl / max(1.0, self._avg_len))
                scores[unit_id] = scores.get(unit_id, 0.0) + idf * (tf * (self.k1 + 1)) / denom
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        return ranked[:top_k]

    def unit(self, unit_id: str) -> TextUnit | None:
        for unit in self.units:
            if unit.unit_id == unit_id:
                return unit
        return None


class LexicalRetriever:
    """BM25 retriever with a typed result."""

    def __init__(self, index: LexicalIndex):
        self.index = index

    def retrieve(self, query: str, *, top_k: int = 8) -> list[TextUnit]:
        ranked = self.index.search(query, top_k=top_k)
        return [self.index.unit(unit_id) for unit_id, _ in ranked if self.index.unit(unit_id)]
