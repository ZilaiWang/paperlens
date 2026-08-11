"""Small-corpus BM25 retrieval implemented in-project for reproducibility."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from ..models import Chunk, SearchHit

TOKEN_RE = re.compile(
    r"[a-z]+(?:-[a-z0-9]+)+|[a-z][a-z0-9_]*|[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?%?|[\u3400-\u9fff]",
    re.IGNORECASE,
)


def tokenize(text: str) -> list[str]:
    """Tokenize Latin words/numbers and add CJK character bigrams."""

    normalized = unicodedata.normalize("NFKC", text).casefold()
    raw = TOKEN_RE.findall(normalized)
    tokens: list[str] = []
    cjk_run: list[str] = []

    def flush_cjk() -> None:
        nonlocal cjk_run
        if cjk_run:
            tokens.extend(cjk_run)
            tokens.extend("".join(cjk_run[index : index + 2]) for index in range(len(cjk_run) - 1))
            cjk_run = []

    for token in raw:
        if re.fullmatch(r"[\u3400-\u9fff]", token):
            cjk_run.append(token)
        else:
            flush_cjk()
            tokens.append(token)
    flush_cjk()
    return tokens


@dataclass(frozen=True, slots=True)
class BM25Config:
    k1: float = 1.5
    b: float = 0.75


class BM25Index:
    """A deterministic Okapi BM25 index for a few hundred paper chunks."""

    def __init__(self, chunks: Iterable[Chunk], config: BM25Config | None = None):
        self.chunks = list(chunks)
        self.config = config or BM25Config()
        self.tokens = [tokenize(chunk.text) for chunk in self.chunks]
        self.term_frequencies = [Counter(tokens) for tokens in self.tokens]
        self.doc_lengths = [len(tokens) for tokens in self.tokens]
        self.average_length = (
            sum(self.doc_lengths) / len(self.doc_lengths) if self.doc_lengths else 0.0
        )
        document_frequency: Counter[str] = Counter()
        for tokens in self.tokens:
            document_frequency.update(set(tokens))
        self.idf = {
            term: math.log(1 + (len(self.chunks) - count + 0.5) / (count + 0.5))
            for term, count in document_frequency.items()
        }

    def scores(self, query: str) -> list[float]:
        query_terms = tokenize(query)
        if not query_terms or not self.chunks:
            return [0.0] * len(self.chunks)
        k1, b = self.config.k1, self.config.b
        average = self.average_length or 1.0
        output: list[float] = []
        for frequencies, length in zip(self.term_frequencies, self.doc_lengths, strict=True):
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                denominator = frequency + k1 * (1 - b + b * length / average)
                score += self.idf.get(term, 0.0) * (frequency * (k1 + 1)) / denominator
            output.append(score)
        return output

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        section_hints: Iterable[str] = (),
        section_multiplier: float = 1.08,
    ) -> list[SearchHit]:
        hints = {hint.casefold() for hint in section_hints if hint}
        scored: list[tuple[int, float]] = []
        for index, raw_score in enumerate(self.scores(query)):
            section = self.chunks[index].section_path.casefold()
            multiplier = (
                section_multiplier if hints and any(hint in section for hint in hints) else 1.0
            )
            scored.append((index, raw_score * multiplier))
        scored.sort(key=lambda item: (-item[1], self.chunks[item[0]].chunk_id))
        return [
            SearchHit(
                chunk=self.chunks[index], lexical_score=score, rrf_score=1 / (60 + rank), rank=rank
            )
            for rank, (index, score) in enumerate(scored[:top_k], start=1)
            if score > 0
        ]


def reciprocal_rank_fusion(
    ranked_lists: Iterable[Iterable[SearchHit]], *, constant: int = 60, top_k: int = 8
) -> list[SearchHit]:
    """Fuse lexical/dense lists while keeping each source score visible."""

    aggregate: defaultdict[str, float] = defaultdict(float)
    representative: dict[str, SearchHit] = {}
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked, start=1):
            aggregate[hit.chunk.chunk_id] += 1 / (constant + rank)
            representative.setdefault(hit.chunk.chunk_id, hit)
    ordered = sorted(aggregate, key=lambda chunk_id: (-aggregate[chunk_id], chunk_id))[:top_k]
    return [
        representative[chunk_id].model_copy(update={"rrf_score": aggregate[chunk_id], "rank": rank})
        for rank, chunk_id in enumerate(ordered, start=1)
    ]


def retrieval_is_sufficient(hits: list[SearchHit], query: str) -> bool:
    """Conservative pre-generation gate based on literal query coverage."""

    if not hits:
        return False
    query_terms = {token for token in tokenize(query) if len(token) > 1 or token.isdigit()}
    if not query_terms:
        return False
    for hit in hits[:5]:
        content_terms = set(tokenize(hit.chunk.text))
        overlap = query_terms & content_terms
        if overlap and (len(overlap) >= 2 or len(query_terms) == 1):
            return True
    return False
