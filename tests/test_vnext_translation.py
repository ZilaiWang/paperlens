"""Translation v2 测试（改进方案1 §六-七 / 改进方案2 §21-24）。

验证：
- 分层 Termbase 优先级：User > Paper > Project > Domain > System
- 锁定译法（lock）与 keep_english
- Translation Memory exact / fuzzy
- 六阶段引擎端到端（StaticJSONModel 离线）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from paperlens_core.termbase.memory import MemoryEntry, TranslationMemory, hash_source
from paperlens_core.termbase.models import TermEntry, TermPolicy, TermScope
from paperlens_core.termbase.termbase import (
    ProjectTermbase,
    SystemTermbase,
    TermResolver,
    UserTermbase,
)


class TestLayeredTermbase:
    def test_priority_user_over_system(self) -> None:
        system = SystemTermbase()
        # system 已有 "backbone" → 骨干网络
        assert system.get("backbone") is not None
        user = UserTermbase(user_id="u1")
        user.upsert(
            TermEntry(
                source="backbone",
                target="主干",
                scope=TermScope.USER,
                confidence=1.0,
                locked=True,
            )
        )
        resolver = TermResolver(system=system, user=user)
        match = resolver.resolve("backbone")
        assert match.target == "主干"
        assert match.scope == TermScope.USER
        assert match.locked

    def test_project_overrides_domain(self) -> None:
        system = SystemTermbase()
        project = ProjectTermbase(project_id="p1")
        project.upsert(
            TermEntry(
                source="proposal",
                target="提案",
                scope=TermScope.PROJECT,
                domain="research",
                confidence=1.0,
            )
        )
        resolver = TermResolver(system=system, project=project)
        # system 有 region proposal，但 proposal 本身只由 project 层提供
        match = resolver.resolve("proposal")
        assert match.matched
        assert match.target == "提案"

    def test_keep_english_policy(self) -> None:
        resolver = TermResolver(system=SystemTermbase())
        entry = TermEntry(
            source="Grounding DINO",
            target="",
            scope=TermScope.SYSTEM,
            keep_english=True,
        )
        resolver.system.upsert(entry)
        match = resolver.resolve("Grounding DINO")
        assert match.policy == TermPolicy.KEEP
        assert match.matched

    def test_system_seed_terms_exist(self) -> None:
        system = SystemTermbase()
        for term in ("feature extractor", "few-shot", "object detection"):
            assert system.get(term) is not None, f"system term {term} missing"


class TestTranslationMemory:
    def _entry(self, source: str, translation: str, paper_id: str = "") -> MemoryEntry:
        return MemoryEntry(
            source_hash=hash_source(source),
            normalized_source=" ".join(source.split()),
            translation=translation,
            paper_id=paper_id,
            quality_score=0.95,
        )

    def test_exact_hit(self) -> None:
        memory = TranslationMemory([self._entry("The model freezes the backbone.", "模型冻结骨干网络。")])
        hit = memory.lookup("The model freezes the backbone.")
        assert hit is not None
        assert hit.exact
        assert hit.translation == "模型冻结骨干网络。"

    def test_normalized_exact_hit_ignores_whitespace(self) -> None:
        memory = TranslationMemory([self._entry("the quick  brown  fox", "敏捷的棕色狐狸")])
        hit = memory.lookup("the quick brown fox")
        assert hit is not None and hit.exact

    def test_fuzzy_returns_context_not_autoapply(self) -> None:
        memory = TranslationMemory(
            [self._entry("We freeze the backbone in stage one.", "我们在第一阶段冻结骨干。")]
        )
        hit = memory.lookup("We freeze the backbone in stage one.")
        assert hit is not None and hit.exact
        # 稍不同的句子：fuzzy 命中作为上下文，exact=False
        fuzzy = memory.lookup("We freeze the backbone in the first stage.")
        assert fuzzy is not None
        assert not fuzzy.exact
        assert fuzzy.similarity > 0

    def test_miss_returns_none(self) -> None:
        memory = TranslationMemory([self._entry("completely different", "完全不同")])
        assert memory.lookup("nothing at all related here") is None


class TestTranslationEngineSixStages:
    def _make_engine(self, model, *, memory=None):
        from paperlens_core.translation_engine.context import ContextCompiler
        from paperlens_core.translation_engine.engine import TranslationEngine

        resolver = TermResolver(system=SystemTermbase())

        def term_snapshot() -> list[dict[str, str]]:
            return [
                {"source": "backbone", "target": "骨干网络", "policy": "translate"},
                {"source": "fine-tuning", "target": "微调", "policy": "translate"},
            ]

        engine = TranslationEngine(
            model,
            context_compiler=ContextCompiler(termbase_snapshot=term_snapshot),
            term_resolver=lambda s: resolver.resolve(s),
            memory_lookup=memory.lookup if memory else None,
            memory_add=memory.add if memory else None,
        )
        return engine

    def test_engine_roundtrip_preserves_citations_and_numbers(self) -> None:

        class StaticModel:
            def __init__(self):
                self.calls = 0

            def invoke_json(self, **kwargs):
                self.calls += 1

                # parse user paragraphs and return faithful translations
                translations = []
                for line in kwargs["user"].split("\n"):
                    if line.startswith("["):
                        translations.append(
                            "我们在骨干网络 [12] 上使用微调，准确率 73.2。"
                        )
                # ensure same length as pending paragraphs
                return type("R", (), {"translations": translations})()

        model = StaticModel()
        engine = self._make_engine(model)
        result = engine.translate_paragraphs(
            paragraphs=["We apply fine-tuning on the backbone [12] and reach 73.2 accuracy."],
            section_title="Method",
            thread_id="t1",
        )
        assert result.translations
        target = result.translations[0]
        assert "[12]" in target          # citation preserved
        assert "73.2" in target          # number preserved
        assert model.calls >= 1
        assert "TRANSLATE" in result.stages_run

    def test_engine_repairs_failed_verification(self) -> None:

        class RepairModel:
            """First call drops the citation (fails verify), repair restores it."""

            def __init__(self):
                self.calls = 0

            def invoke_json(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return type("R", (), {"translations": ["我们在骨干网络上微调。"]})()
                return type("R", (), {"translations": ["我们在骨干网络 [12] 上微调。"]})()

        model = RepairModel()
        engine = self._make_engine(model)
        result = engine.translate_paragraphs(
            paragraphs=["We fine-tune the backbone [12]."],
            section_title="Method",
            thread_id="t2",
        )
        # repair stage ran and restored the citation
        assert "REPAIR" in result.stages_run
        assert result.repaired_indices == [0]
        assert "[12]" in result.translations[0]
        assert result.verify_reports[0].passed

    def test_invalid_repair_is_not_saved_to_memory(self) -> None:
        class BrokenModel:
            def invoke_json(self, **kwargs):
                return type("R", (), {"translations": ["仍然丢失引文。"]})()

        memory = TranslationMemory()
        engine = self._make_engine(BrokenModel(), memory=memory)
        result = engine.translate_paragraphs(
            paragraphs=["Keep this citation [12]."],
            section_title="Method",
        )
        assert not result.verify_reports[0].passed
        assert memory.lookup("Keep this citation [12].") is None

    def test_exact_memory_skips_translator_call(self) -> None:

        class CountingModel:
            def __init__(self):
                self.calls = 0

            def invoke_json(self, **kwargs):
                self.calls += 1
                return type("R", (), {"translations": ["should not be used"]})()

        memory = TranslationMemory(
            [
                MemoryEntry(
                    source_hash=hash_source("Repeat the exact same sentence [12] here."),
                    normalized_source="repeat the exact same sentence [12] here.",
                    translation="在此重复完全相同的句子 [12]。",
                    quality_score=1.0,
                )
            ]
        )
        model = CountingModel()
        engine = self._make_engine(model, memory=memory)
        result = engine.translate_paragraphs(
            paragraphs=["Repeat the exact same sentence [12] here."],
            section_title="Intro",
            thread_id="t3",
        )
        assert model.calls == 0  # exact memory hit → no model call
        assert result.translations[0] == "在此重复完全相同的句子 [12]。"


class TestProtectorAndVerifier:
    def test_protector_extracts_citations_formulas_numbers(self) -> None:
        from paperlens_core.translation_engine.protector import Protector

        source = "See [12, 14] and $E=mc^2$; accuracy is 73.2."
        protector = Protector()
        protected, tokens = protector.protect(source)
        assert any(t.kind == "citation" for t in tokens)
        assert any(t.kind == "formula" for t in tokens)
        assert any(t.kind == "number" for t in tokens)
        # placeholders present, originals shielded
        assert "{{P0}}" in protected
        assert "[12, 14]" not in protected

    def test_restore_tokens_roundtrip(self) -> None:
        from paperlens_core.translation_engine.protector import Protector, restore_tokens

        source = "See [12, 14]."
        protector = Protector()
        protected, tokens = protector.protect(source)
        restored = restore_tokens(protected, tokens)
        assert restored == source

    def test_verifier_flags_lost_citation(self) -> None:
        from paperlens_core.translation_engine.protector import Protector
        from paperlens_core.translation_engine.verifier import DeterministicVerifier

        source = "We freeze the backbone [12]."
        protector = Protector()
        protected, tokens = protector.protect(source)
        report = DeterministicVerifier().verify(protected, "我们冻结骨干网络。", tokens)
        assert not report.passed
        assert any(issue.kind == "CITATION_LOST" for issue in report.errors)

    def test_verifier_passes_when_tokens_survive(self) -> None:
        from paperlens_core.translation_engine.protector import Protector, restore_tokens
        from paperlens_core.translation_engine.verifier import DeterministicVerifier

        source = "See [12, 14] and $E=mc^2$."
        protector = Protector()
        protected, tokens = protector.protect(source)
        # 模拟忠实翻译：占位符全部保留（还原原文后 round-trip）
        faithful = restore_tokens(protected, tokens)
        report = DeterministicVerifier().verify(protected, faithful, tokens)
        assert report.passed

    def test_repair_planner_selects_failed_indices(self) -> None:
        from paperlens_core.translation_engine.repair import RepairPlanner
        from paperlens_core.translation_engine.verifier import VerifyReport

        reports = [
            VerifyReport(passed=False, issues=[{"kind": "CITATION_LOST", "detail": "x", "severity": "ERROR"}]),
            VerifyReport(passed=True, issues=[]),
            VerifyReport(passed=False, issues=[{"kind": "NUMBER_LOST", "detail": "y", "severity": "ERROR"}]),
        ]
        indices = RepairPlanner().plan(reports)
        assert indices == [0, 2]
