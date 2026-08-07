"""Actual LangChain tools exposed to the bounded PaperLens workflows."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from .database import Database
from .references import parse_references
from .retrieval import BM25Index

_database: Database | None = None


def configure_tools(database: Database) -> None:
    """Bind tools to one local repository; call once during app/CLI startup."""

    global _database
    _database = database


def _db() -> Database:
    if _database is None:
        raise RuntimeError("PAPERLENS_TOOLS_NOT_CONFIGURED")
    return _database


@tool
def search_passages(paper_id: str, query: str, top_k: int = 8) -> dict[str, Any]:
    """Search paragraph chunks in one already-ingested paper; returns page-located hits only."""

    query = query.strip()
    if not query:
        return {"ok": False, "error_code": "EMPTY_QUERY", "hits": []}
    paper = _db().get_paper(paper_id)
    if paper is None:
        return {"ok": False, "error_code": "PAPER_NOT_FOUND", "hits": []}
    hits = BM25Index(_db().get_chunks(paper_id)).search(query, top_k=max(1, min(top_k, 20)))
    return {
        "ok": True,
        "paper_id": paper_id,
        "hits": [
            {
                "chunk_id": hit.chunk.chunk_id,
                "pdf_page_start": hit.chunk.page_start,
                "pdf_page_end": hit.chunk.page_end,
                "section": hit.chunk.section_path,
                "text": hit.chunk.text,
                "lexical_score": round(hit.lexical_score, 6),
            }
            for hit in hits
        ],
    }


@tool
def get_passage(paper_id: str, chunk_id: str) -> dict[str, Any]:
    """Fetch one exact chunk, rejecting IDs that belong to another paper."""

    for chunk in _db().get_chunks(paper_id):
        if chunk.chunk_id == chunk_id:
            return {
                "ok": True,
                "paper_id": paper_id,
                "chunk_id": chunk_id,
                "pdf_page_start": chunk.page_start,
                "pdf_page_end": chunk.page_end,
                "section": chunk.section_path,
                "block_ids": chunk.block_ids,
                "text": chunk.text,
            }
    return {"ok": False, "error_code": "CHUNK_NOT_FOUND_FOR_PAPER"}


@tool
def audit_references(paper_id: str, allow_network: bool = False) -> dict[str, Any]:
    """Run local IEEE-numeric reference lint; network verification needs a separate HITL gate."""

    paper = _db().get_paper(paper_id)
    if paper is None:
        return {"ok": False, "error_code": "PAPER_NOT_FOUND"}
    reference_text = "\n".join(
        block.text
        for block in _db().get_blocks(paper_id)
        if "reference" in block.section_path.casefold()
        or "bibliography" in block.section_path.casefold()
    )
    records = parse_references(reference_text)
    return {
        "ok": True,
        "paper_id": paper_id,
        "style_rule": "IEEE_NUMERIC_V1",
        "network_status": "CONSENT_REQUIRED" if allow_network else "LOCAL_ONLY",
        "records": [record.model_dump(mode="json") for record in records],
    }


@tool
def compare_papers(paper_ids: list[str], fields: list[str]) -> dict[str, Any]:
    """Validate a 2-3 paper comparison request and report per-paper extraction readiness."""

    if not 2 <= len(paper_ids) <= 3 or len(set(paper_ids)) != len(paper_ids):
        return {"ok": False, "error_code": "COMPARE_REQUIRES_2_OR_3_UNIQUE_PAPERS"}
    missing = [paper_id for paper_id in paper_ids if _db().get_paper(paper_id) is None]
    if missing:
        return {"ok": False, "error_code": "PAPER_NOT_FOUND", "paper_ids": missing}
    return {
        "ok": True,
        "paper_ids": paper_ids,
        "fields": fields,
        "workflow": "EXTRACT_EACH_PAPER_THEN_ASSEMBLE",
        "chunk_counts": {paper_id: len(_db().get_chunks(paper_id)) for paper_id in paper_ids},
    }


PAPERLENS_TOOLS = [search_passages, get_passage, audit_references, compare_papers]
