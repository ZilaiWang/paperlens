"""Retrieval (V1 compatibility + Hybrid vNext).

The original ``retrieval.py`` module was migrated into ``retrieval.v1`` so the
package can coexist with the v2 HybridRetriever.  All V1 call sites
(``from .retrieval import BM25Index``) keep working through re-exports here.

V2 (改进方案1 §二十二): ``HybridRetriever`` composes lexical + optional dense +
section prior via RRF; the evidence contract is unchanged.
"""

from .hybrid import (
    HybridRetriever,
    HybridSearchResult,
    fusion_rrf,
    rank_fusion,
)
from .lexical import LexicalIndex, LexicalRetriever, TextUnit
from .v1 import (
    TOKEN_RE,
    BM25Config,
    BM25Index,
    reciprocal_rank_fusion,
    retrieval_is_sufficient,
)
from .v1 import (
    tokenize as v1_tokenize,
)

__all__ = [
    "BM25Config",
    "BM25Index",
    "TOKEN_RE",
    "reciprocal_rank_fusion",
    "retrieval_is_sufficient",
    "v1_tokenize",
    "HybridRetriever",
    "HybridSearchResult",
    "fusion_rrf",
    "rank_fusion",
    "LexicalIndex",
    "LexicalRetriever",
    "TextUnit",
]
