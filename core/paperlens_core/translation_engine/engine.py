"""TranslationEngine — six-stage orchestration (改进方案2 §24).

    [1] ContextCompiler   → ContextPack
    [2] TermResolver      → per-batch term snapshot (from Termbase)
    [3] Protector         → protect citations/formulas/numbers
    [4] Translator        → model call
    [5] Verifier          → deterministic + semantic
    [6] Selective Repair  → re-translate failed units with repair instruction

The engine is model-agnostic: any object exposing ``invoke_json(**kwargs)``
works (OpenAICompatibleModel, StaticJSONModel).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel

from .context import ContextCompiler
from .protector import ProtectedToken, Protector, restore_tokens
from .repair import RepairPlanner
from .verifier import DeterministicVerifier, VerifyReport


class _BatchResult(BaseModel):
    """Model schema for the translator stage."""

    translations: list[str]


class TranslationStage(str):
    CONTEXT = "CONTEXT"
    TERMS = "TERMS"
    PROTECT = "PROTECT"
    TRANSLATE = "TRANSLATE"
    VERIFY = "VERIFY"
    REPAIR = "REPAIR"


@dataclass
class TranslationJobResult:
    """Output of translating one batch of paragraphs."""

    translations: list[str] = field(default_factory=list)
    issues: list[list[str]] = field(default_factory=list)
    verify_reports: list[VerifyReport] = field(default_factory=list)
    protected_tokens: list[list[ProtectedToken]] = field(default_factory=list)
    repaired_indices: list[int] = field(default_factory=list)
    memory_hits: list[str] = field(default_factory=list)
    term_snapshot: list[dict[str, str]] = field(default_factory=list)
    stages_run: list[str] = field(default_factory=list)


class TranslationEngine:
    """Compose the six stages for one batch of paragraphs."""

    def __init__(
        self,
        model: object,
        *,
        context_compiler: ContextCompiler | None = None,
        protector: Protector | None = None,
        verifier: DeterministicVerifier | None = None,
        repair_planner: RepairPlanner | None = None,
        term_resolver: Callable[[str], Any] | None = None,
        memory_lookup: Callable[[str], Any] | None = None,
        memory_add: Callable[[Any], None] | None = None,
        max_repairs: int = 10,
    ):
        self.model = model
        self.context_compiler = context_compiler or ContextCompiler()
        self.protector = protector or Protector()
        self.verifier = verifier or DeterministicVerifier()
        self.repair_planner = repair_planner or RepairPlanner(max_repairs=max_repairs)
        self.term_resolver = term_resolver
        self.memory_lookup = memory_lookup
        self.memory_add = memory_add

    # ------------------------------------------------------------------
    def translate_paragraphs(
        self,
        *,
        paragraphs: list[str],
        section_title: str = "",
        section_id: str | None = None,
        paper_title: str = "",
        thread_id: str = "",
        stage: str = "translation_v2",
        neighbor_context: list[str] | None = None,
    ) -> TranslationJobResult:
        result = TranslationJobResult()

        # [1] context
        result.stages_run.append(TranslationStage.CONTEXT)
        pack = self.context_compiler.compile(
            paragraph=paragraphs[0] if paragraphs else "",
            paragraph_index=0,
            section_id=section_id,
            section_title=section_title,
            neighbor_context=neighbor_context,
            paper_title=paper_title,
        )
        result.term_snapshot = pack.termbase_snapshot

        # [2] terms + [3] protect, per paragraph
        result.stages_run.append(TranslationStage.TERMS)
        term_blocks: list[str] = []
        if pack.termbase_snapshot:
            for item in pack.termbase_snapshot:
                policy = item.get("policy", "translate")
                term_blocks.append(f"{item.get('source')} → {item.get('target')} ({policy})")

        result.stages_run.append(TranslationStage.PROTECT)
        protected_paragraphs: list[tuple[str, list[ProtectedToken]]] = []
        for paragraph in paragraphs:
            protected, tokens = self.protector.protect(paragraph)
            protected_paragraphs.append((protected, tokens))
            result.protected_tokens.append(tokens)

        # [4] translate (whole batch in one call, protected text)
        result.stages_run.append(TranslationStage.TRANSLATE)
        protected_texts = [p for p, _ in protected_paragraphs]

        # memory: exact-hit reuse for paragraphs that already exist
        memory_hits: dict[int, str] = {}
        if self.memory_lookup is not None:
            for index, paragraph in enumerate(paragraphs):
                hit = self.memory_lookup(paragraph)
                if hit is not None and getattr(hit, "exact", False):
                    memory_hits[index] = hit.translation
                    result.memory_hits.append("EXACT")
                else:
                    result.memory_hits.append("MISS")

        pending = [
            index for index in range(len(paragraphs)) if index not in memory_hits
        ]
        targets: list[str] = [
            memory_hits.get(index, "") for index in range(len(paragraphs))
        ]

        if pending:
            pending_texts = [protected_texts[index] for index in pending]
            rendered_context = pack.render()
            schema = _BatchResult
            response = self.model.invoke_json(
                system=(
                    "You are a scientific English→Chinese translator.\n"
                    + rendered_context
                    + "\nTranslate each paragraph faithfully. Keep protected "
                    "placeholders {{P0}} etc. exactly as they are. "
                    "Return JSON {\"translations\": [...]}."
                ),
                user="\n\n".join(
                    f"[{i}]\n{text}" for i, text in enumerate(pending_texts)
                ),
                schema=schema,
                stage=stage,
                thread_id=thread_id,
            )
            translated_list = list(response.translations)
            for offset, original_index in enumerate(pending):
                if offset < len(translated_list):
                    targets[original_index] = translated_list[offset]

        # [5] verify
        result.stages_run.append(TranslationStage.VERIFY)
        reports: list[VerifyReport] = []
        for index, (paragraph, tokens) in enumerate(protected_paragraphs):
            if targets[index]:
                report = self.verifier.verify(paragraph, targets[index], tokens)
            else:
                report = VerifyReport(
                    passed=False,
                    issues=[
                        {
                            "kind": "MISSING",
                            "detail": "翻译未生成",
                            "severity": "ERROR",
                        }
                    ],
                )
            reports.append(report)
        # [6] selective repair
        repair_indices = self.repair_planner.plan(reports)
        if repair_indices:
            result.stages_run.append(TranslationStage.REPAIR)
            for index in repair_indices:
                source = protected_texts[index]
                instruction = self.repair_planner.instruction(reports[index])
                repair_schema = _BatchResult
                response = self.model.invoke_json(
                    system=(
                        "Repair this scientific translation. Fix ONLY the "
                        f"reported issues: {instruction}. "
                        'Return JSON {"translations": ["..."]}.'
                    ),
                    user=f"SOURCE:\n{source}\n\nPREVIOUS TARGET:\n{targets[index] or '(none)'}",
                    schema=repair_schema,
                    stage=f"{stage}_repair",
                    thread_id=thread_id,
                )
                repaired = response.translations[0] if response.translations else ""
                if repaired:
                    targets[index] = repaired
                    result.repaired_indices.append(index)
                    reports[index] = self.verifier.verify(
                        protected_texts[index], repaired, protected_paragraphs[index][1]
                    )

        result.verify_reports = reports
        result.issues = [[issue.detail for issue in report.errors] for report in reports]

        # Restore protected tokens (citations/formulas/numbers) into the final
        # translations.  The model must never see raw numbers/citations leave
        # the engine as placeholders — this is the round-trip the verifier
        # validated above.
        restored_targets: list[str] = []
        for index, _paragraph in enumerate(paragraphs):
            _, tokens = protected_paragraphs[index]
            raw_target = targets[index] or ""
            restored_targets.append(
                restore_tokens(raw_target, tokens)
                if tokens else raw_target
            )
        result.translations = restored_targets

        # store into memory (restored text, so exact hits on re-translation work)
        if self.memory_add is not None:
            from .memory_adapter import memory_entry_from_batch

            for index, paragraph in enumerate(paragraphs):
                if restored_targets[index] and reports[index].passed:
                    entry = memory_entry_from_batch(paragraph, restored_targets[index])
                    self.memory_add(entry)

        return result
