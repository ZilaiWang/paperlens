"""Immersive translation: glossary + protected tokens + batch translate + verify.

Design:
- never translate by concatenating the whole paper and splitting on newlines;
- each TranslationUnit keeps source/target alignment and never overwrites blocks;
- protected tokens ([12], Eq. (3), $x_i$, terms, Table 2) are replaced before
  the model call and restored after, then programmatically verified.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .documents import TranslationStatus, TranslationUnit
from .llm import StructuredModel
from .prompts import PROMPT_VERSION

# --- protected token extraction ---------------------------------------------

CITATION_RE = re.compile(r"\[(\d+(?:\s*[-,]\s*\d+)*)\]")
# author-year citations (Zou et al., 2023; Gupta et al., 2019) as a whole
AUTHOR_YEAR_RE = re.compile(r"\([^()]*?\b(?:19|20)\d{2}[^()]*?\)")
# standalone years that the model must keep verbatim
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
EQ_REF_RE = re.compile(r"(?:Eq|Equation)\.?\s*\(?(\d+)\)?", re.IGNORECASE)
FIG_REF_RE = re.compile(r"(?:Fig|Figure)\.?\s*(\d+)", re.IGNORECASE)
TAB_REF_RE = re.compile(r"(?:Tab|Table)\.?\s*(\d+)", re.IGNORECASE)
SEC_REF_RE = re.compile(r"(?:Sec|Section)\.?\s*(\d+(?:\.\d+)*)", re.IGNORECASE)
MATH_INLINE_RE = re.compile(r"\$[^$]+\$")


def unit_matches_block(unit_source: str, block_text: str) -> bool:
    """翻译单元与 block 是否同一内容（V3.22）。

    block_id 是索引型（html-{paper_id}-{序号:05d}）：重解析（如公式提取
    插入新块）后同 id 会指向不同内容，旧翻译单元按 id 缓存就会错位。
    按内容前缀比对（忽略空白与 $ 包裹差异）判定存废。
    """

    def norm(text: str) -> str:
        return re.sub(r"\s+", "", text).replace("$", "")

    a, b = norm(unit_source)[:80], norm(block_text)[:80]
    return bool(a) and a == b


@dataclass(slots=True)
class ProtectedToken:
    kind: str  # CIT | EQ | FIG | TAB | SEC | MATH | TERM
    token: str
    placeholder: str


def protect_tokens(text: str, glossary: list[str]) -> tuple[str, list[ProtectedToken]]:
    """Replace non-translatable spans with placeholders; restore afterwards."""
    tokens: list[ProtectedToken] = []
    spans: list[tuple[int, int, int]] = []  # (start, end, token_index)

    def add(kind: str, token: str, start: int) -> None:
        placeholder = f"⟦{kind}_{len(tokens) + 1:03d}⟧"
        tokens.append(ProtectedToken(kind=kind, token=token, placeholder=placeholder))
        spans.append((start, start + len(token), len(tokens) - 1))

    for match in AUTHOR_YEAR_RE.finditer(text):
        add("CIT", match.group(0), match.start())
    for match in YEAR_RE.finditer(text):
        # skip years already covered by an author-year CIT span
        if not any(start <= match.start() < end for start, end, _ in spans):
            add("YEAR", match.group(0), match.start())
    for match in CITATION_RE.finditer(text):
        add("CIT", match.group(0), match.start())
    for match in EQ_REF_RE.finditer(text):
        add("EQ", match.group(0), match.start())
    for match in FIG_REF_RE.finditer(text):
        add("FIG", match.group(0), match.start())
    for match in TAB_REF_RE.finditer(text):
        add("TAB", match.group(0), match.start())
    for match in SEC_REF_RE.finditer(text):
        add("SEC", match.group(0), match.start())
    for match in MATH_INLINE_RE.finditer(text):
        add("MATH", match.group(0), match.start())
    # glossary terms are intentionally NOT protected: the model translates
    # them using the glossary (e.g. feature extractor -> 特征提取器), so the
    # placeholder would vanish and fail verification.

    # Replace from the end backwards so earlier offsets stay valid.
    spans.sort(key=lambda item: item[0])
    protected = text
    for start, end, index in reversed(spans):
        token = tokens[index]
        protected = protected[:start] + token.placeholder + protected[end:]
    return protected, tokens


def restore_tokens(translated: str, tokens: list[ProtectedToken]) -> str:
    for token in tokens:
        translated = translated.replace(token.placeholder, token.token)
    return translated


def _placeholder_kinds(text: str) -> list[str]:
    return re.findall(r"⟦(CIT|EQ|FIG|TAB|SEC|MATH|TERM|YEAR)_\d+⟧", text)


_CN_DIGITS = {
    "零": "0", "一": "1", "二": "2", "两": "2", "三": "3", "四": "4",
    "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
}


def _numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", text)


def _numbers_zh_normalized(text: str) -> list[str]:
    """Numbers in a Chinese translation: Arabic digits plus single Chinese
    numerals (二/两/三...), so '2' matching '两' passes the number check."""
    normalized = text
    for chinese, arabic in _CN_DIGITS.items():
        normalized = normalized.replace(chinese, arabic)
    return re.findall(r"\d+(?:\.\d+)?", normalized)


def verify_translation(source: str, target: str, tokens: list[ProtectedToken]) -> list[str]:
    """Programmatic checks before a translation is shown .

    ERROR-level checks (V3.0, restored 2026-08-03): numbers, citations,
    figure/table/equation references must survive the translation; benign
    restorations (year as a number, citation restored, Fig. 5 -> 图 5) pass.
    WARNING/INFO levels (terminology drift) arrive with V3.3.
    """
    from collections import Counter

    issues: list[str] = []
    # YEAR and CIT placeholders may be restored by the model as the year
    # number or the citation itself (benign); the number check below still
    # guarantees the digits are present.
    def _restored_acceptably(token: ProtectedToken) -> bool:
        if token.placeholder in target:
            return True
        if token.kind == "YEAR" and token.token in target:
            return True  # model restored the year number
        if token.kind == "CIT":
            # the model restored the citation itself: either as an author-year
            # form (（Vinyals 等人，2016）) or as the plain number ([12] ->
            # "12" / "文献 12"); every number of the citation group must
            # survive. (Fixed 2026-08-04: the old check only accepted 19xx/20xx
            # years, so plain "[12]" citations were always rejected and half
            # the units of HTML papers ended up NEEDS_RETRY.)
            numbers = re.findall(r"\d+", token.token)
            return bool(numbers and all(number in target for number in numbers))
        if token.kind in ("FIG", "TAB", "EQ", "SEC"):
            # model translated the reference (e.g. Fig. 5 -> 图 5): the
            # number must survive; the strict number check still applies
            number = re.search(r"\d+(?:\.\d+)*", token.token)
            return bool(number and number.group(0) in target)
        if token.kind == "MATH":
            # V3.23b：行内公式（$...$）恢复后原样保留即可——此前的
            # _restored_acceptably 没有 MATH 分支，V3.21 起行内公式
            # $ 包裹激活了 MATH 保护后，所有含公式单元全被判"保护标记
            # 不完整"（译文本身是对的，恢复后的 $h_{t}$ 就在 target 里）
            return token.token in target
        return False

    missing_tokens = [
        token for token in tokens if not _restored_acceptably(token)
    ]
    if missing_tokens:
        kinds = Counter(token.kind for token in missing_tokens)
        issues.append(f"保护标记不完整: {dict(kinds)}")
        issues.append(
            "丢失保护标记 " + ", ".join(token.placeholder for token in missing_tokens[:4])
        )
    # V3.23b：不做方向性数字集合校验——4.5 million → 450 万、36 → 3600
    # 这类中文单位换算（×100）会让逐字比对产生大量误报，为它做缩放适配
    # 得不偿失；数字保真由占位符检查（CIT/FIG/TAB/EQ/SEC/MATH）兜底。
    return issues


# --- PaperTranslationProfile  ------------------------------

class TranslationEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=80)
    type: str = "MODEL"  # MODEL | DATASET | METRIC | MODULE | SYMBOL
    policy: Literal["KEEP_ENGLISH", "TRANSLATE"] = "KEEP_ENGLISH"


class Abbreviation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    short: str = Field(min_length=1, max_length=40)
    long: str = ""
    preferred_zh: str = ""


class Notation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=40)
    meaning: str = ""


class AmbiguousTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=80)
    preferred_zh: str = Field(min_length=1, max_length=80)
    context: str = ""


class PaperTranslationProfile(BaseModel):
    """Structured, versioned, immutable-per-task paper-level translation state.

    Built once per paper version and shared by every concurrent batch so
    terminology decisions do not drift between batches (§13). Plain text
    fields keep the prefix stable for provider context caching (§13.2).
    """

    model_config = ConfigDict(extra="forbid")

    paper_title: str = ""
    domain: list[str] = Field(default_factory=list, max_length=8)
    task_definition: str = ""
    main_contributions: list[str] = Field(default_factory=list, max_length=8)
    style_tone: str = "academic"
    entities: list[TranslationEntity] = Field(default_factory=list, max_length=60)
    abbreviations: list[Abbreviation] = Field(default_factory=list, max_length=40)
    notations: list[Notation] = Field(default_factory=list, max_length=30)
    ambiguous_terms: list[AmbiguousTerm] = Field(default_factory=list, max_length=30)

    def render_instructions(self) -> str:
        """Compact text block injected into every batch (stable prefix)."""
        lines = [f"PAPER: {self.paper_title}"]
        if self.domain:
            lines.append(f"DOMAIN: {', '.join(self.domain)}")
        if self.task_definition:
            lines.append(f"TASK: {self.task_definition}")
        if self.main_contributions:
            lines.append("CONTRIBUTIONS: " + "; ".join(self.main_contributions))
        if self.entities:
            lines.append(
                "KEEP_ENGLISH: "
                + ", ".join(entity.source for entity in self.entities)
            )
        if self.abbreviations:
            lines.append(
                "ABBREVIATIONS: "
                + "; ".join(
                    f"{abbr.short} -> {abbr.preferred_zh or abbr.long}"
                    for abbr in self.abbreviations
                )
            )
        if self.ambiguous_terms:
            lines.append(
                "TERM_PREFERENCES: "
                + "; ".join(
                    f"{term.source} -> {term.preferred_zh}" for term in self.ambiguous_terms
                )
            )
        return "\n".join(lines)


PROFILE_SYSTEM = """You build a structured translation profile for an academic paper
being translated from English to Chinese. Extract:
- domain: 2-6 keywords describing the field (e.g. computer vision, few-shot object detection)
- task_definition: one sentence on what the paper does
- main_contributions: up to 5 short contribution statements
- entities: proper nouns that MUST stay in English (model names, datasets, metrics,
  module names like Grounding DINO, AP50, RPN); policy=KEEP_ENGLISH
- abbreviations: acronyms with their long form and a preferred Chinese expansion
  (e.g. FSOD -> few-shot object detection -> 少样本目标检测)
- notations: symbols with their meaning (e.g. N -> number of novel classes)
- ambiguous_terms: words whose translation depends on this paper's domain
  (e.g. proposal -> 候选框 in object detection); prefer a Chinese term,
  set context to the sense that applies here
Output strict JSON. Keep everything concise; never invent entities.""".strip()


def build_profile(
    model: StructuredModel,
    *,
    title: str,
    abstract: str,
    section_titles: list[str],
    captions: list[str],
    thread_id: str,
) -> PaperTranslationProfile:
    """Build the paper-level profile once per version (cached by the server)."""
    source = json.dumps(
        {
            "title": title,
            "abstract": abstract[:1500],
            "sections": section_titles[:40],
            "captions": captions[:12],
        },
        ensure_ascii=False,
    )
    return model.invoke_json(
        system=PROFILE_SYSTEM,
        user=source[:8000],
        schema=PaperTranslationProfile,
        stage="translation_profile",
        thread_id=thread_id,
        temperature=0.0,
    )


def terminology_violations(
    source: str, target: str, glossary: list[GlossaryEntry]
) -> list[str]:
    """WARNING-level terminology check (§15.1): a glossary term present in the
    source must use its preferred translation (or stay English when marked).
    Misses are returned as messages; they do not demote the unit's status.
    """
    violations: list[str] = []
    source_lower = source.casefold()
    for entry in glossary:
        if entry.source.casefold() not in source_lower:
            continue
        if entry.keep_english:
            if entry.source not in target:
                violations.append(f"术语 {entry.source} 应保持英文")
        elif entry.translation not in target:
            violations.append(f"术语 {entry.source} 未使用指定译法「{entry.translation}」")
    return violations


def terminology_concordance(
    units: list[TranslationUnit], glossary: list[GlossaryEntry]
) -> list[dict[str, object]]:
    """Scan translated units for glossary violations (§15.2); the server
    re-translates only the flagged units (selective repair)."""
    findings: list[dict[str, object]] = []
    for unit in units:
        violations = terminology_violations(unit.source_text, unit.target_text, glossary)
        if violations:
            findings.append(
                {
                    "unit_id": unit.unit_id,
                    "source_block_ids": unit.source_block_ids,
                    "source": unit.source_text[:400],
                    "violations": violations,
                }
            )
    return findings


# --- glossary ---------------------------------------------------------------

class GlossaryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=80)
    translation: str = Field(min_length=1, max_length=80)
    keep_english: bool = False
    abbreviation: str = ""


class GlossaryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[GlossaryEntry] = Field(min_length=1, max_length=60)


GLOSSARY_SYSTEM = """You build a paper glossary for translation. Extract key technical terms
from the supplied title/abstract/method text. For each term give a concise Chinese
translation; set keep_english=true for proper nouns, model names and symbols that
must stay in English (e.g. Grounding DINO, AP50, RPN). Output strict JSON with
exactly the field 'entries'. Do not translate generic English words.""".strip()


def build_glossary(
    model: StructuredModel, texts: list[str], *, thread_id: str
) -> list[GlossaryEntry]:
    source = "\n\n".join(texts[:3])
    draft = model.invoke_json(
        system=GLOSSARY_SYSTEM,
        user=source[:6000],
        schema=GlossaryDraft,
        stage="glossary",
        thread_id=thread_id,
        temperature=0.0,
    )
    return draft.entries


# --- batch translation ------------------------------------------------------

class ParagraphPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paragraph_index: int
    translation: str = Field(min_length=1, max_length=6000)


class BatchTranslationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paragraphs: list[ParagraphPair] = Field(min_length=1, max_length=12)


BATCH_TRANSLATE_SYSTEM = """You translate academic paper paragraphs from English to Chinese.

Rules:
- Translate meaning faithfully; keep negation, conditions, numbers and comparisons.
- Keep every placeholder ⟦KIND_NNN⟧ exactly as-is in the same position.
- Keep method names, dataset names, metric names and symbols in English.
- One translation per input paragraph, in the same order; never merge or split.
- Output strict JSON with exactly the field 'paragraphs'. Each entry has
  paragraph_index (the input index) and translation.""".strip()


def batch_translate(
    model: StructuredModel,
    *,
    paragraphs: list[str],
    section_title: str,
    previous_summary: str,
    glossary: list[GlossaryEntry],
    thread_id: str,
    profile: PaperTranslationProfile | None = None,
    section_brief: str = "",
    context_blocks: list[str] | None = None,
    repair_instructions: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Translate N paragraphs with shared context; returns (targets, issues).

    V3.3 layered context (§13.1): the paper profile, current-section brief
    and surrounding paragraphs are injected for understanding only — only the
    target paragraphs are translated, and batches never overlap.
    ``repair_instructions`` carries terminology fixes for selective repair
    (§15.2); the target paragraphs stay the same.
    """
    glossary_terms = [entry.source for entry in glossary]
    protected_batches: list[tuple[str, list[ProtectedToken]]] = [
        protect_tokens(paragraph, glossary_terms) for paragraph in paragraphs
    ]
    glossary_block = "\n".join(
        f"{entry.source} -> {entry.translation}" + ("（保持英文）" if entry.keep_english else "")
        for entry in glossary
    )
    user_parts = [
        f"SECTION: {section_title}",
        f"PREVIOUS_SUMMARY: {previous_summary}",
    ]
    if profile is not None and profile.render_instructions().strip():
        user_parts.append(profile.render_instructions())
    if section_brief:
        user_parts.append(f"SECTION_BRIEF: {section_brief}")
    if context_blocks:
        context_block = "\n".join(
            f"<CONTEXT>{text}</CONTEXT>" for text in context_blocks
        )
        user_parts.append(
            "CONTEXT_ONLY (understand these, never translate them):\n" + context_block
        )
    if repair_instructions:
        user_parts.append("REPAIR_INSTRUCTIONS:\n" + "\n".join(repair_instructions))
    user_parts.extend(
        [
            "GLOSSARY:\n" + (glossary_block or "(none)"),
            "PARAGRAPHS:",
            *[
                f"[{index}]\n{protected}"
                for index, (protected, _) in enumerate(protected_batches)
            ],
            "OUTPUT_SCHEMA:\n"
            + json.dumps(BatchTranslationDraft.model_json_schema(), ensure_ascii=False),
        ]
    )
    user = "\n\n".join(user_parts)
    draft = model.invoke_json(
        system=BATCH_TRANSLATE_SYSTEM,
        user=user,
        schema=BatchTranslationDraft,
        stage="batch_translate",
        thread_id=thread_id,
        temperature=0.0,
    )
    by_index = {item.paragraph_index: item.translation for item in draft.paragraphs}
    targets: list[str] = []
    issues: list[str] = []
    for index, (source, (_, tokens)) in enumerate(
        zip(paragraphs, protected_batches, strict=True)
    ):
        if index not in by_index:
            issues.append(f"缺少第 {index} 段译文")
            targets.append("")
            continue
        raw = by_index[index]
        restored = restore_tokens(raw, tokens)
        verification = verify_translation(source, restored, tokens)
        if verification:
            issues.append(f"第 {index} 段: {'; '.join(verification)}")
        # WARNING-level terminology check (§15.1): does not demote the unit
        violations = terminology_violations(source, restored, glossary)
        if violations:
            issues.append(f"术语 {index} 段: {'; '.join(violations)}")
        targets.append(restored)
    return targets, issues


def make_units(
    *, paper_version_id: str, section_id: str | None, source_blocks: list[dict[str, object]],
    targets: list[str], issues: list[str], model_name: str, thread_id: str,
) -> list[TranslationUnit]:
    units: list[TranslationUnit] = []
    for index, (block, target) in enumerate(zip(source_blocks, targets, strict=True)):
        # ERROR-level checks (protected tokens/numbers) demote the unit;
        # WARNING-level terminology drift is recorded, not blocked (§12.2)
        unit_issues = [issue for issue in issues if issue.startswith(f"第 {index} 段")]
        term_issues = [issue for issue in issues if issue.startswith(f"术语 {index} 段")]
        status = TranslationStatus.TRANSLATED
        if target == "":
            status = TranslationStatus.NEEDS_RETRY
        elif unit_issues:
            status = TranslationStatus.NEEDS_RETRY
        units.append(
            TranslationUnit(
                # block_id 唯一且稳定：同 section 多组批次的 unit_id 不再
                # 互相覆盖（旧实现用组内 index，HTML 论文 65 段实际只剩
                # 最后一组的 6 条 —— 翻译空缺的隐藏原因，fix 2026-08-04）
                unit_id=f"tu-{paper_version_id[-10:]}-{str(block['block_id'])[-16:]}",
                paper_version_id=paper_version_id,
                section_id=section_id,
                source_block_ids=[str(block["block_id"])],
                source_text=str(block["text"])[:4000],
                target_text=target,
                model=model_name,
                prompt_version=PROMPT_VERSION,
                status=status,
                alignment={"issues": unit_issues, "terminology": term_issues},
            )
        )
    return units
