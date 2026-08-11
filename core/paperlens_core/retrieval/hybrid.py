"""HybridRetriever: combine lexical + optional dense + section prior via RRF.

改进方案1 §二十二:

    Query → lexical + dense + section-aware prior + entity-aware → RRF → reranker
    → Evidence Ledger

The evidence contract (unit_id + quote + locator) stays identical regardless
of how the retriever is composed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .lexical import LexicalIndex, TextUnit


def fusion_rrf(rankings: list[list[str]], *, k: int = 60) -> dict[str, float]:
    """Reciprocal rank fusion over multiple ranked id lists."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, unit_id in enumerate(ranking, start=1):
            scores[unit_id] = scores.get(unit_id, 0.0) + 1.0 / (k + rank)
    return scores


def rank_fusion(
    rankings: list[list[str]],
    *,
    top_k: int = 10,
    k: int = 60,
) -> list[str]:
    scores = fusion_rrf(rankings, k=k)
    return [unit_id for unit_id, _ in sorted(scores.items(), key=lambda i: i[1], reverse=True)[:top_k]]


@dataclass
class HybridSearchResult:
    unit: TextUnit
    score: float = 0.0
    rank: int = 0
    sources: list[str] = field(default_factory=list)  # "lexical" | "dense" | "section"

    def as_dict(self) -> dict[str, object]:
        return {
            "unit_id": self.unit.unit_id,
            "paper_version_id": self.unit.paper_version_id,
            "text": self.unit.text,
            "score": round(self.score, 4),
            "rank": self.rank,
            "sources": self.sources,
            "section_path": self.unit.section_path,
            "page": self.unit.page,
            "metadata": self.unit.metadata,
        }


class HybridRetriever:
    """Compose lexical, dense and section-prior retrieval into one result set.

    dense_retriever and section_prior are optional callables:

        dense_retriever(query) -> list[str]  (unit ids)
        section_prior(section_query) -> list[str]  (unit ids)
    """

    def __init__(
        self,
        index: LexicalIndex,
        *,
        dense_retriever: Callable[[str], list[str]] | None = None,
        section_prior: Callable[[str], list[str]] | None = None,
        top_k: int = 10,
    ):
        self.index = index
        self.dense_retriever = dense_retriever
        self.section_prior = section_prior
        self.top_k = top_k

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        section_query: str = "",
    ) -> list[HybridSearchResult]:
        top_k = top_k or self.top_k
        rankings: list[list[str]] = []
        sources: dict[str, list[str]] = {}

        lexical = [unit_id for unit_id, _ in self.index.search(query, top_k=top_k * 3)]
        if lexical:
            rankings.append(lexical)
            for unit_id in lexical:
                sources.setdefault(unit_id, []).append("lexical")

        if self.dense_retriever is not None:
            try:
                dense = self.dense_retriever(query)[: top_k * 3]
                if dense:
                    rankings.append(dense)
                    for unit_id in dense:
                        sources.setdefault(unit_id, []).append("dense")
            except Exception:  # noqa: BLE001 - dense is optional
                pass

        if section_query and self.section_prior is not None:
            try:
                section = self.section_prior(section_query)[: top_k * 3]
                if section:
                    rankings.append(section)
                    for unit_id in section:
                        sources.setdefault(unit_id, []).append("section")
            except Exception:  # noqa: BLE001 - optional
                pass

        if not rankings:
            return []

        fused = fusion_rrf(rankings)
        ranked_ids = sorted(fused, key=lambda uid: fused[uid], reverse=True)[:top_k]
        results: list[HybridSearchResult] = []
        for rank, unit_id in enumerate(ranked_ids, start=1):
            unit = self.index.unit(unit_id)
            if unit is None:
                continue
            results.append(
                HybridSearchResult(
                    unit=unit,
                    score=round(fused[unit_id], 4),
                    rank=rank,
                    sources=sources.get(unit_id, ["rrf"]),
                )
            )
        return results
