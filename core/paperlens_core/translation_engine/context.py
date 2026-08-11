"""ContextCompiler: assemble the translation context pack (改进方案2 §24 [1]).

Inputs: paper profile, section summary, neighbor context, termbase snapshot,
symbols / abbreviations.  The output ContextPack is passed to the translator
so every batch translation sees the same structured context instead of a
freeform prompt.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field


class ContextPack(BaseModel):
    """Structured context for one translation batch."""

    model_config = ConfigDict(extra="allow")

    paper_title: str = ""
    section_title: str = ""
    section_brief: str = ""            # first paragraph of the section
    neighbor_context: list[str] = Field(default_factory=list)  # prev/next paras
    termbase_snapshot: list[dict[str, str]] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    abbreviations: list[dict[str, str]] = Field(default_factory=list)
    domain: list[str] = Field(default_factory=list)
    # metadata for audit
    profile_version: str = ""
    termbase_version: str = ""

    def render(self) -> str:
        """Render the pack into the deterministic instruction block."""
        lines: list[str] = []
        if self.paper_title:
            lines.append(f"PAPER: {self.paper_title}")
        if self.section_title:
            lines.append(f"SECTION: {self.section_title}")
        if self.section_brief:
            lines.append(f"BRIEF: {self.section_brief[:200]}")
        if self.neighbor_context:
            lines.append("CONTEXT:")
            for item in self.neighbor_context:
                lines.append(f"  · {item[:200]}")
        if self.termbase_snapshot:
            lines.append("TERMS:")
            for term in self.termbase_snapshot:
                lines.append(
                    f"  {term.get('source')} -> {term.get('target')}"
                    f" ({term.get('policy', 'translate')})"
                )
        if self.symbols:
            lines.append(f"SYMBOLS: {' '.join(self.symbols)}")
        if self.abbreviations:
            lines.append("ABBREVIATIONS:")
            for abbr in self.abbreviations:
                lines.append(f"  {abbr.get('short')} = {abbr.get('long')} -> {abbr.get('preferred_zh', '')}")
        return "\n".join(lines)


class ContextCompiler:
    """Deterministically build a ContextPack for a paragraph batch."""

    def __init__(
        self,
        *,
        profile_loader: Callable[[], Any] | None = None,
        termbase_snapshot: Callable[[], list[dict[str, str]]] | None = None,
        section_brief_loader: Callable[[str], str] | None = None,
    ):
        self.profile_loader = profile_loader
        self.termbase_snapshot = termbase_snapshot or (lambda: [])
        self.section_brief_loader = section_brief_loader or (lambda _section_id: "")

    def compile(
        self,
        *,
        paragraph: str,
        paragraph_index: int,
        section_id: str | None,
        section_title: str,
        neighbor_context: list[str] | None = None,
        paper_title: str = "",
    ) -> ContextPack:
        profile = None
        if self.profile_loader is not None:
            try:
                profile = self.profile_loader()
            except Exception:  # noqa: BLE001 - profile is an enhancement
                profile = None

        section_brief = (
            self.section_brief_loader(section_id) if section_id else ""
        )

        domain = list(getattr(profile, "domain", []) or []) if profile else []
        abbreviations = list(getattr(profile, "abbreviations", []) or []) if profile else []
        symbols = list(getattr(profile, "symbols", []) or []) if profile else []

        return ContextPack(
            paper_title=paper_title,
            section_title=section_title,
            section_brief=section_brief,
            neighbor_context=neighbor_context or [],
            termbase_snapshot=self.termbase_snapshot(),
            symbols=symbols,
            abbreviations=[
                dict(item) for item in abbreviations
            ] if abbreviations else [],
            domain=domain,
            profile_version=str(getattr(profile, "version", "")),
        )
