"""Layered termbase with priority resolution.

Priority: User > Paper > Project > Domain > System (改进方案1 §六).

All layers share the same in-memory dict shape (``source -> TermEntry``).
A resolver layers them by scope priority and picks the highest-priority match
for an occurrence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import TermEntry, TermMatch, TermPolicy, TermScope

# Scope priority: lower number = higher priority
_SCOPE_PRIORITY = {
    TermScope.USER: 0,
    TermScope.PAPER: 1,
    TermScope.PROJECT: 2,
    TermScope.DOMAIN: 3,
    TermScope.SYSTEM: 4,
}


@dataclass
class LockMode:
    """Which layers a "lock" propagates to (改进方案2 §21)."""

    paper: bool = True
    project: bool = True
    domain: bool = False
    user: bool = False


class _TermLayer:
    """A single term dictionary layer."""

    def __init__(self, scope: TermScope):
        self.scope = scope
        self._terms: dict[str, TermEntry] = {}

    def upsert(self, entry: TermEntry) -> None:
        self._terms[entry.source.lower()] = entry

    def get(self, source: str) -> TermEntry | None:
        return self._terms.get(source.lower())

    def remove(self, source: str) -> bool:
        return self._terms.pop(source.lower(), None) is not None

    def all(self) -> list[TermEntry]:
        return list(self._terms.values())

    def __len__(self) -> int:
        return len(self._terms)


class SystemTermbase:
    """Built-in terminology (never user-editable by default)."""

    def __init__(self) -> None:
        self._layer = _TermLayer(TermScope.SYSTEM)
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        defaults = [
            TermEntry(source="region proposal", target="候选框", domain="object_detection",
                      sense="region proposal", confidence=0.98, scope=TermScope.SYSTEM),
            TermEntry(source="feature extractor", target="特征提取器", domain="cv",
                      confidence=0.98, scope=TermScope.SYSTEM),
            TermEntry(source="backbone", target="骨干网络", domain="cv",
                      confidence=0.96, scope=TermScope.SYSTEM),
            TermEntry(source="fine-tuning", target="微调", domain="ml",
                      confidence=0.97, scope=TermScope.SYSTEM),
            TermEntry(source="few-shot", target="少样本", domain="ml",
                      confidence=0.95, scope=TermScope.SYSTEM),
            TermEntry(source="object detection", target="目标检测", domain="cv",
                      confidence=0.99, scope=TermScope.SYSTEM),
            TermEntry(source="ground truth", target="真值", domain="ml",
                      confidence=0.96, scope=TermScope.SYSTEM),
        ]
        for entry in defaults:
            self.upsert(entry)

    def upsert(self, entry: TermEntry) -> None:
        entry.scope = TermScope.SYSTEM
        self._layer.upsert(entry)

    def get(self, source: str) -> TermEntry | None:
        return self._layer.get(source)

    def all(self) -> list[TermEntry]:
        return self._layer.all()


class DomainTermbase(_TermLayer):
    def __init__(self, domain: str = ""):
        super().__init__(TermScope.DOMAIN)
        self.domain = domain


class ProjectTermbase(_TermLayer):
    def __init__(self, project_id: str = ""):
        super().__init__(TermScope.PROJECT)
        self.project_id = project_id


class UserTermbase(_TermLayer):
    def __init__(self, user_id: str = ""):
        super().__init__(TermScope.USER)
        self.user_id = user_id


class TermResolver:
    """Resolve a term occurrence across layers by priority."""

    def __init__(
        self,
        *,
        system: SystemTermbase | None = None,
        domain: DomainTermbase | None = None,
        project: ProjectTermbase | None = None,
        paper: _TermLayer | None = None,
        user: UserTermbase | None = None,
    ):
        self.system = system or SystemTermbase()
        self.domain = domain
        self.project = project
        self.paper = paper
        self.user = user

    def resolve(self, source: str) -> TermMatch:
        candidates: list[tuple[int, TermEntry]] = []
        layers = [
            (TermScope.USER, self.user),
            (TermScope.PAPER, self.paper),
            (TermScope.PROJECT, self.project),
            (TermScope.DOMAIN, self.domain),
            (TermScope.SYSTEM, self.system),
        ]
        for scope, layer in layers:
            if layer is None:
                continue
            entry = layer.get(source)
            if entry is not None:
                candidates.append((_SCOPE_PRIORITY[scope], entry))
        if not candidates:
            return TermMatch(source=source, target="", scope=TermScope.SYSTEM,
                             policy=TermPolicy.TRANSLATE, matched=False)
        priority, entry = min(candidates, key=lambda item: item[0])
        policy = entry.effective_policy
        return TermMatch(
            source=source,
            target=entry.target,
            scope=entry.scope,
            policy=policy,
            confidence=entry.confidence,
            locked=entry.locked,
            matched=True,
        )

    def resolve_all(self, terms: Iterable[str]) -> dict[str, TermMatch]:
        return {term: self.resolve(term) for term in terms}

    def upsert(self, entry: TermEntry, *, layer: TermScope | None = None) -> None:
        """Write into a specific layer (default: honor entry.scope)."""
        target_layer = layer or entry.scope
        if target_layer == TermScope.SYSTEM:
            self.system.upsert(entry)
        elif target_layer == TermScope.DOMAIN and self.domain is not None:
            self.domain.upsert(entry)
        elif target_layer == TermScope.PROJECT and self.project is not None:
            self.project.upsert(entry)
        elif target_layer == TermScope.PAPER and self.paper is not None:
            self.paper.upsert(entry)
        elif target_layer == TermScope.USER and self.user is not None:
            self.user.upsert(entry)
        else:
            raise ValueError(f"layer {target_layer} not configured on resolver")


def resolve_term(
    source: str,
    *,
    system: SystemTermbase | None = None,
    domain: DomainTermbase | None = None,
    project: ProjectTermbase | None = None,
    paper: _TermLayer | None = None,
    user: UserTermbase | None = None,
) -> TermMatch:
    """Convenience one-shot resolver."""
    resolver = TermResolver(
        system=system, domain=domain, project=project, paper=paper, user=user
    )
    return resolver.resolve(source)
