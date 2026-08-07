"""Evidence ledger construction and fail-closed claim validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .models import AnswerClaim, AnswerDraft, EvidenceItem, EvidenceLink, GroundedAnswer, SearchHit
from .utils import normalize_space, sha256_text

NUMBER_RE = re.compile(r"(?<!\w)[−–-]?[+]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][−–-]?\d+)?\s*%?")
# English negation words are matched as whole tokens only, never as substrings:
# "not" must not fire on "annotation" and "no" must not fire on "novel"/"normalization".
# Academic English expresses negation without "not" in common ways (fail to ...,
# ignores ..., unreliable, difficult to ..., cannot, prevent ...); including them here
# is a deliberate calibration so that Chinese claims asserting 不/未/无法 are not
# falsely rejected when the cited sentence supports them through these forms.
NEGATIONS_EN = {
    "no", "not", "never", "without", "neither", "nor",
    "fail", "fails", "failed", "failure", "failures",
    "unable", "cannot", "can not", "prevent", "prevents", "prevented",
    "ignore", "ignores", "ignored", "ignoring", "lack", "lacks", "lacking",
    "unreliable", "unreliability", "inconsistent", "insufficient", "unnecessary",
    "unstable", "impossible", "difficult", "hardly", "rarely", "avoid", "avoids",
    "avoided", "unavoidable",
}
# Chinese negations map to the shared semantic set: the check is "the claim asserts a
# negation, and the cited sentence must express negation in some recognized form".
# The semantic attribution verifier remains the second gate for anything this misses.
NEGATIONS_ZH = {
    word: set(NEGATIONS_EN)
    for word in ("不", "没有", "没", "未", "无", "无需", "不用", "避免", "无法", "不能", "难以")
}
NEGATIONS_ZH["忽略"] = NEGATIONS_ZH["不"] | {"ignore", "ignores", "ignored", "ignoring"}
NEGATIONS = NEGATIONS_EN | set(NEGATIONS_ZH)
COMPARATORS = {
    "higher",
    "lower",
    "increase",
    "decrease",
    "outperform",
    "improve",
    "worse",
    "drop",
    "drops",
    "dropped",
    "decline",
    "declines",
    "declined",
    "高于",
    "低于",
    "提高",
    "下降",
}
_EN_TOKEN_RE = re.compile(r"[a-z]+")
# Sentence boundary requires a capital letter / Chinese character / quote after the
# separator, so "e.g.", "et al." and "p.3" never split a sentence.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。！？])\s+(?=[A-Z\"'“‘一-鿿])")


def _negation_flags(text: str) -> set[str]:
    """Negation concepts in ``text``: English tokens matched whole-word, Chinese
    negations as ``zh:<word>`` markers with non-overlapping matching so that
    ``无需`` consumes ``无`` instead of flagging both."""
    flags: set[str] = set()
    lowered = text.casefold()
    flags.update(token for token in _EN_TOKEN_RE.findall(lowered) if token in NEGATIONS_EN)
    consumed: list[tuple[int, int]] = []
    for chinese_word in sorted(NEGATIONS_ZH, key=len, reverse=True):
        start = 0
        while (pos := text.find(chinese_word, start)) != -1:
            span = (pos, pos + len(chinese_word))
            if not any(a <= pos < b for a, b in consumed):
                flags.add(f"zh:{chinese_word}")
                consumed.append(span)
            start = pos + 1
    return flags


def _negation_context_mismatch(claim_text: str, context: str) -> bool:
    """True when the claim asserts a negation that the cited context does not
    support. A Chinese negation is supported if any of its English forms appears
    in the context (``没有`` accepts either ``no`` or ``not``). The reverse
    direction - context negates, claim does not - is left to the semantic
    attribution verifier, which reads the full passage."""
    claim_flags = _negation_flags(claim_text)
    context_flags = _negation_flags(context)
    for flag in claim_flags:
        if flag in context_flags:
            continue
        if flag.startswith("zh:") and context_flags & NEGATIONS_ZH[flag[3:]]:
            continue
        return True
    return False


def _quote_sentence_context(excerpt: str, char_start: int, char_end: int) -> str:
    """The sentence(s) of ``excerpt`` containing the quote span ``[start, end)``.

    The negation/comparison context must be scoped to what the claim actually points
    at: a 1,200-2,400 character chunk almost always contains unrelated "not"/"without",
    which would otherwise reject every claim citing it.
    """
    bounds = [0] + [m.end() for m in _SENTENCE_BOUNDARY.finditer(excerpt)] + [len(excerpt)]
    start = max(bound for bound in bounds if bound <= char_start)
    end = min(bound for bound in bounds if bound >= char_end)
    return excerpt[start:end]


def build_evidence_ledger(question_id: str, hits: list[SearchHit]) -> list[EvidenceItem]:
    ledger: list[EvidenceItem] = []
    for hit in hits:
        excerpt = hit.chunk.text
        evidence_id = f"ev-{hit.chunk.paper_version_id}-{sha256_text(hit.chunk.chunk_id + excerpt)[:12]}"  # V4.1：统一 DocumentGraph，用 paper_version_id
        ledger.append(
            EvidenceItem(
                evidence_id=evidence_id,
                question_id=question_id,
                paper_id=hit.chunk.paper_id,
                chunk_id=hit.chunk.chunk_id,
                block_ids=hit.chunk.block_ids,
                verbatim_excerpt=excerpt,
                page_start=hit.chunk.page_start,
                page_end=hit.chunk.page_end,
                section_path=hit.chunk.section_path,
                lexical_score=hit.lexical_score,
                dense_score=hit.dense_score,
                rrf_score=hit.rrf_score,
                segments=[segment.model_dump(mode="json") for segment in hit.chunk.segments],
            )
        )
    return ledger


def locate_chunk_spans(
    segments: list[dict[str, object]],
    char_start: int,
    char_end: int,
) -> list[dict[str, object]]:
    """Map a verified quote span inside a chunk back to source blocks.

    改进方案2.md §16.1: a quote at chunk chars 330-438 resolves to its block,
    block char range, page and physical bboxes so the frontend can highlight
    the exact span in the immersive reader and overlay it on the PDF.
    """
    locators: list[dict[str, object]] = []
    for segment in segments:
        segment_start = int(segment["chunk_char_start"])
        segment_end = int(segment["chunk_char_end"])
        overlap_start = max(char_start, segment_start)
        overlap_end = min(char_end, segment_end)
        if overlap_start >= overlap_end:
            continue
        # clip the block-local range to the overlap (segments are single
        # blocks; the quote may cover several adjacent blocks)
        block_start = int(segment["block_char_start"]) + (overlap_start - segment_start)
        block_end = block_start + (overlap_end - overlap_start)
        locators.append(
            {
                "block_id": segment["block_id"],
                "block_char_start": block_start,
                "block_char_end": block_end,
                "page": segment["page"],
                "bboxes": [list(bbox) for bbox in segment.get("bboxes", [])],
            }
        )
    return locators


def _normalized_number(value: str) -> tuple[Decimal, bool] | None:
    value = value.strip().replace("−", "-").replace("–", "-").replace(" ", "")
    percentage = value.endswith("%")
    if percentage:
        value = value[:-1]
    try:
        return Decimal(value), percentage
    except InvalidOperation:
        return None


def numbers_in(text: str) -> list[tuple[Decimal, bool]]:
    return [number for match in NUMBER_RE.findall(text) if (number := _normalized_number(match))]


def _word_flags(text: str, vocabulary: set[str]) -> set[str]:
    lowered = text.casefold()
    return {word for word in vocabulary if word in lowered}


@dataclass(slots=True)
class ClaimCheck:
    claim: AnswerClaim
    accepted: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GuardResult:
    accepted: list[AnswerClaim]
    rejected: list[ClaimCheck]


class EvidenceGuard:
    """Validate provable attribution properties; semantic verdict is separate."""

    def __init__(self, ledger: list[EvidenceItem]):
        self.ledger = {item.evidence_id: item for item in ledger}

    def _validate_link(self, link: EvidenceLink) -> tuple[EvidenceLink | None, list[str]]:
        evidence = self.ledger.get(link.evidence_id)
        if evidence is None:
            return None, ["UNKNOWN_EVIDENCE_ID"]
        excerpt = evidence.verbatim_excerpt
        if link.char_end > len(excerpt):
            return None, ["QUOTE_SPAN_OUT_OF_RANGE"]
        literal = excerpt[link.char_start : link.char_end]
        if literal != link.verbatim_quote:
            # Local models frequently return a correct literal quote but inaccurate offset.
            occurrences = [
                match.start() for match in re.finditer(re.escape(link.verbatim_quote), excerpt)
            ]
            if len(occurrences) == 1:
                start = occurrences[0]
                link = link.model_copy(
                    update={"char_start": start, "char_end": start + len(link.verbatim_quote)}
                )
            else:
                return None, ["QUOTE_NOT_UNIQUE_LITERAL_SUBSTRING"]
        locators = locate_chunk_spans(evidence.segments, link.char_start, link.char_end)
        return (
            link.model_copy(
                update={
                    "quote_sha256": sha256_text(link.verbatim_quote),
                    "locators": locators,
                }
            ),
            [],
        )

    def check_claim(self, claim: AnswerClaim) -> ClaimCheck:
        reasons: list[str] = []
        valid_links: list[EvidenceLink] = []
        evidence_texts: list[str] = []
        for link in claim.evidence_links:
            checked_link, link_reasons = self._validate_link(link)
            reasons.extend(link_reasons)
            if checked_link:
                valid_links.append(checked_link)
                evidence_texts.append(self.ledger[checked_link.evidence_id].verbatim_excerpt)
        if not valid_links:
            reasons.append("CLAIM_HAS_NO_VALID_EVIDENCE")

        evidence_text = "\n".join(evidence_texts)
        evidence_numbers = numbers_in(evidence_text)
        for number in numbers_in(claim.text):
            if number not in evidence_numbers:
                reasons.append(f"NUMBER_NOT_IN_EVIDENCE:{number[0]}{'%' if number[1] else ''}")

        # Negation is checked directionally and scoped to the quoted sentence(s):
        # every negation the claim asserts must be supportable inside the cited span.
        # The reverse direction (evidence negates, claim does not) is left to the
        # semantic attribution verifier, which can read the full context.
        context = "\n".join(
            _quote_sentence_context(
                self.ledger[link.evidence_id].verbatim_excerpt, link.char_start, link.char_end
            )
            for link in valid_links
        )
        if _negation_context_mismatch(claim.text, context):
            reasons.append("NEGATION_CONTEXT_MISMATCH")
        claim_comparison = _word_flags(claim.text, COMPARATORS)
        evidence_comparison = _word_flags(evidence_text, COMPARATORS)
        if claim_comparison and not evidence_comparison:
            reasons.append("COMPARISON_DIRECTION_UNSUPPORTED")

        if reasons:
            return ClaimCheck(claim=claim, accepted=False, reasons=sorted(set(reasons)))
        return ClaimCheck(
            claim=claim.model_copy(update={"evidence_links": valid_links}), accepted=True
        )

    def validate(self, draft: AnswerDraft) -> GuardResult:
        checks = [self.check_claim(claim) for claim in draft.claims]
        return GuardResult(
            accepted=[check.claim for check in checks if check.accepted],
            rejected=[check for check in checks if not check.accepted],
        )

    def finalize(
        self, draft: AnswerDraft, *, semantic_verified_ids: set[str] | None = None
    ) -> GroundedAnswer:
        result = self.validate(draft)
        if semantic_verified_ids is not None:
            newly_rejected = [
                ClaimCheck(claim=claim, accepted=False, reasons=["ATTRIBUTION_NOT_SUPPORTED"])
                for claim in result.accepted
                if claim.claim_id not in semantic_verified_ids
            ]
            result.rejected.extend(newly_rejected)
            result.accepted = [
                claim for claim in result.accepted if claim.claim_id in semantic_verified_ids
            ]
        accepted_by_id = {claim.claim_id: claim for claim in result.accepted}
        summary_claims = [
            accepted_by_id[cid].text
            for cid in draft.answer_summary_claim_ids
            if cid in accepted_by_id
        ]
        if not summary_claims:
            summary_claims = [claim.text for claim in result.accepted]
        answer = (
            "\n\n".join(summary_claims) if summary_claims else "当前证据不足，无法给出可靠回答。"
        )
        return GroundedAnswer(
            answer=answer,
            claims=result.accepted,
            # V3.16: draft 不再输出 coverage_notes，后端填空（前端无展示）
            coverage_notes=[],
            rejected_claims=[
                {"claim_id": check.claim.claim_id, "reasons": check.reasons}
                for check in result.rejected
            ],
        )


def render_evidence_label(item: EvidenceItem, short_name: str = "Paper") -> str:
    page = (
        f"p.{item.page_start}"
        if item.page_start == item.page_end
        else f"pp.{item.page_start}-{item.page_end}"
    )
    return f"[{short_name}, PDF {page}, {normalize_space(item.section_path)}]"
