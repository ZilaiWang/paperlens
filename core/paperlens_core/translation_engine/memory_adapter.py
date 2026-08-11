"""Small adapter helpers between the engine and TranslationMemory."""

from __future__ import annotations

from ..termbase.memory import MemoryEntry, hash_source, normalize_space


def memory_entry_from_batch(
    source: str,
    translation: str,
    *,
    paper_id: str = "",
    project_id: str = "",
    model: str = "",
    quality_score: float = 0.9,
) -> MemoryEntry:
    return MemoryEntry(
        source_hash=hash_source(source),
        normalized_source=normalize_space(source),
        translation=translation,
        paper_id=paper_id,
        project_id=project_id,
        model=model,
        quality_score=quality_score,
    )
