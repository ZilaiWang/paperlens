"""Layered Termbase + Translation Memory (改进方案1 §六-七 / 改进方案2 §21-24).

TermEntry: a term is not just ``source -> target`` but carries domain, sense,
policy, scope, lock and provenance.  Termbase resolves terms by priority:

    User > Paper > Project > Domain > System

TranslationMemory reuses exact-hash translations and only *suggests* fuzzy
matches as context (never auto-overwrites).
"""

from .memory import MemoryHit, TranslationMemory, memory_hit_kind
from .models import (
    TermEntry,
    TermEntryUpsert,
    TermPack,
    TermPackManifest,
    TermPolicy,
    TermScope,
)
from .packs import TermPackCatalog
from .termbase import (
    DomainTermbase,
    LockMode,
    ProjectTermbase,
    SystemTermbase,
    TermResolver,
    UserTermbase,
    resolve_term,
)

__all__ = [
    "TranslationMemory",
    "MemoryHit",
    "memory_hit_kind",
    "TermEntry",
    "TermPolicy",
    "TermScope",
    "TermEntryUpsert",
    "TermPack",
    "TermPackManifest",
    "TermPackCatalog",
    "DomainTermbase",
    "LockMode",
    "ProjectTermbase",
    "SystemTermbase",
    "TermResolver",
    "UserTermbase",
    "resolve_term",
]
