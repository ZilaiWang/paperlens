"""Default research tools (改进方案2 Phase H §46).

Three real tools with typed outputs:
- search: lexical retrieval over a corpus of TextUnits
- profile: build a PaperProfile for a paper
- compare: run Comparison v2 alignment across papers
"""

from __future__ import annotations

from typing import Callable

from .runtime import ToolContext, ToolRegistry, ToolResult, ToolSpec


def build_default_registry(
    *,
    corpus: list[object] | None = None,
    profile_builder: object | None = None,
    profile_fn: Callable[[list[str]], list[dict[str, object]]] | None = None,
    search_fn: Callable[[str], list[dict[str, object]]] | None = None,
    compare_fn: Callable[[list[str]], dict[str, object]] | None = None,
) -> ToolRegistry:
    """Build a registry wired to the caller's data layer.

    If a callable is not provided, the tool returns a structured "unavailable"
    result instead of crashing — the DAG can still complete with a clear note.
    """
    registry = ToolRegistry()

    def search_handler(context: ToolContext) -> ToolResult:
        query = str(context.params.get("query", ""))
        top_k = int(context.params.get("top_k", 5))
        if search_fn is not None:
            results = search_fn(query)[:top_k]
            return ToolResult(
                data={"query": query, "results": results, "count": len(results)}
            )
        if corpus is None:
            return ToolResult(
                ok=False,
                data={"query": query, "results": [], "count": 0},
                error="search tool not wired (no corpus)",
            )
        from ..retrieval.hybrid import HybridRetriever
        from ..retrieval.lexical import LexicalIndex, TextUnit

        units = [u for u in corpus if isinstance(u, TextUnit)] or [
            TextUnit(
                unit_id=getattr(u, "unit_id", str(i)),
                paper_version_id=getattr(u, "paper_version_id", ""),
                text=getattr(u, "text", ""),
                section_path=getattr(u, "section_path", ""),
                page=getattr(u, "page", 0),
            )
            for i, u in enumerate(corpus)
        ]
        if not units:
            return ToolResult(ok=False, error="empty corpus")
        index = LexicalIndex().build(units)
        retriever = HybridRetriever(index, top_k=top_k)
        results = [
            r.as_dict() for r in retriever.search(query, top_k=top_k)
        ]
        return ToolResult(
            data={"query": query, "results": results, "count": len(results)}
        )

    def profile_handler(context: ToolContext) -> ToolResult:
        paper_ids = [str(item) for item in context.params.get("paper_ids", []) or []]
        paper_id = str(context.params.get("paper_id", ""))
        if paper_id and not paper_ids:
            paper_ids = [paper_id]
        sections = context.params.get("sections") or {}
        if not paper_ids:
            return ToolResult(ok=False, error="profile tool needs paper_ids")
        if profile_fn is not None:
            profiles = profile_fn(paper_ids)
            return ToolResult(data={"profiles": profiles, "count": len(profiles)})
        if profile_builder is None:
            return ToolResult(
                ok=False,
                data={"paper_ids": paper_ids},
                error="profile tool not wired (no profile_builder)",
            )
        profile = profile_builder.build_offline(
            paper_id=paper_ids[0],
            paper_version_id=paper_ids[0],
            title=str(context.params.get("title", "")),
            abstract=str(context.params.get("abstract", "")),
            sections=dict(sections),
        )
        return ToolResult(data={"paper_id": paper_ids[0], "profile": profile.model_dump(mode="json")})

    def compare_handler(context: ToolContext) -> ToolResult:
        paper_ids = list(context.params.get("paper_ids", []) or [])
        if not paper_ids:
            return ToolResult(ok=False, error="compare tool needs paper_ids")
        if compare_fn is not None:
            data = compare_fn(paper_ids)
            return ToolResult(data=data)
        return ToolResult(
            ok=False,
            data={"paper_ids": paper_ids},
            error="compare tool not wired (no compare_fn)",
        )

    registry.register(ToolSpec("search", "Lexical retrieval over the corpus", search_handler))
    registry.register(ToolSpec("profile", "Build a paper profile", profile_handler))
    registry.register(ToolSpec("compare", "Align results across papers", compare_handler))
    return registry
