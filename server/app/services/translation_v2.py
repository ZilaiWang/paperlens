"""Translation v2 service: wires the termbase + translation memory + engine.

This service is the bridge that makes the layered termbase and the six-stage
engine reachable from the API (改进方案1 §六-七 / 改进方案2 §21-24, 900 行附近
"术语库真正进入使用体验").
"""

from __future__ import annotations

from paperlens_core.termbase.memory import MemoryEntry, TranslationMemory
from paperlens_core.termbase.models import TermEntry, TermScope
from paperlens_core.termbase.packs import TermPackCatalog
from paperlens_core.termbase.termbase import (
    DomainTermbase,
    ProjectTermbase,
    SystemTermbase,
    TermResolver,
    UserTermbase,
)
from paperlens_core.translation_engine.context import ContextCompiler
from paperlens_core.translation_engine.engine import TranslationEngine
from paperlens_core.translation_engine.verifier import DeterministicVerifier

from ..repositories import VNextRepository


class TranslationV2Service:
    """Build a wired engine per workspace from stored termbase/memory rows."""

    def __init__(self, vnext: VNextRepository):
        self.vnext = vnext

    # ------------------------------------------------------------------
    def load_termbase(self, workspace_id: str) -> dict[str, object]:
        """Assemble a layered TermResolver from the stored entries."""
        system = SystemTermbase()
        domain = DomainTermbase(domain="installed-packs")
        project = ProjectTermbase(project_id=workspace_id)
        user = UserTermbase(user_id=workspace_id)

        rows = self.vnext.list_term_entries(workspace_id, scope=None)
        for row in rows:
            entry = TermEntry(
                source=row["source"],
                target=row["target"],
                domain=row["domain"],
                sense=row["sense"],
                scope=TermScope(row["scope"]),
                policy=row["policy"],
                locked=row["locked"],
                keep_english=row["keep_english"],
                confidence=row["confidence"],
            )
            scope = entry.scope
            if scope == TermScope.PROJECT:
                project.upsert(entry)
            elif scope == TermScope.USER:
                user.upsert(entry)
            elif scope == TermScope.SYSTEM:
                system.upsert(entry)

        catalog = TermPackCatalog()
        for entry in catalog.entries(self.vnext.list_installed_term_packs(workspace_id)):
            domain.upsert(entry)

        resolver = TermResolver(system=system, domain=domain, project=project, user=user)
        return {"resolver": resolver, "project": project, "domain": domain, "system": system}

    # ------------------------------------------------------------------
    def load_memory(self, workspace_id: str) -> TranslationMemory:
        memory = TranslationMemory()
        for row in self.vnext.memory_entries(workspace_id, limit=2000):
            memory.add(MemoryEntry(**row))
        return memory

    # ------------------------------------------------------------------
    def build_engine(self, model: object, workspace_id: str) -> TranslationEngine:
        termbase = self.load_termbase(workspace_id)
        resolver = termbase["resolver"]
        memory = self.load_memory(workspace_id)

        # a snapshot of project + system terms (the ones the user curates)
        def term_snapshot_curated() -> list[dict[str, str]]:
            snapshot: list[dict[str, str]] = []
            for entry in (
                list(termbase["project"].all())
                + list(termbase["domain"].all())
                + list(termbase["system"].all())
            ):
                policy = entry.effective_policy
                snapshot.append(
                    {
                        "source": entry.source,
                        "target": entry.target,
                        "policy": policy.value if hasattr(policy, "value") else str(policy),
                    }
                )
            return snapshot

        def memory_lookup(source: str):
            return memory.lookup(source)

        def memory_add(entry) -> None:
            data = entry.model_dump(mode="json") if hasattr(entry, "model_dump") else dict(entry)
            self.vnext.save_memory_entry(workspace_id, data)

        engine = TranslationEngine(
            model,
            context_compiler=ContextCompiler(termbase_snapshot=term_snapshot_curated),
            term_resolver=lambda source: resolver.resolve(source),
            memory_lookup=memory_lookup,
            memory_add=memory_add,
            verifier=DeterministicVerifier(strict_numbers=True),
        )
        return engine

    # ------------------------------------------------------------------
    def resolve_terms_in_text(self, workspace_id: str, text: str) -> list[dict[str, object]]:
        """Scan a text and return every known term occurrence (UI hover data)."""
        termbase = self.load_termbase(workspace_id)
        hits: list[dict[str, object]] = []
        lower = text.lower()
        for entry in (
            list(termbase["project"].all())
            + list(termbase["domain"].all())
            + list(termbase["system"].all())
        ):
            source = entry.source.lower()
            if source and source in lower:
                hits.append(
                    {
                        "source": entry.source,
                        "target": entry.target,
                        "scope": entry.scope.value,
                        "policy": entry.effective_policy.value if hasattr(entry.effective_policy, "value") else str(entry.effective_policy),
                        "locked": entry.locked,
                        "count": lower.count(source),
                    }
                )
        hits.sort(key=lambda item: -item["count"])
        return hits
