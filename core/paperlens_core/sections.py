"""Rule-based section recognition and block assignment."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Block, BlockType, Section
from .utils import normalize_match_text, sha256_text

CANONICAL_TITLES: dict[str, tuple[str, ...]] = {
    "abstract": ("abstract", "summary", "摘要"),
    "introduction": ("introduction", "motivation", "引言", "绪论"),
    "background": ("background", "preliminaries", "背景", "预备知识"),
    "related_work": ("related work", "literature review", "相关工作", "文献综述"),
    "method": ("method", "methods", "methodology", "approach", "model", "方法", "方法论"),
    "experiments": (
        "experiment",
        "experiments",
        "experimental setup",
        "evaluation",
        "实验",
        "评估",
    ),
    "results": ("result", "results", "findings", "结果"),
    "discussion": ("discussion", "analysis", "讨论", "分析"),
    "limitations": ("limitation", "limitations", "局限", "局限性"),
    "conclusion": (
        "conclusion",
        "conclusions",
        "concluding remarks",
        "final remarks",
        "结论",
    ),
    "references": ("reference", "references", "bibliography", "参考文献"),
    "appendix": ("appendix", "appendices", "supplementary material", "附录"),
    "acknowledgements": (
        "acknowledgement",
        "acknowledgements",
        "acknowledgment",
        "acknowledgments",
        "致谢",
    ),
}

# Generic patterns shared across ML/CV papers. These must never be demo-paper
# specific strings: they describe recurring section semantics ("ablation" is an
# experiments subsection, "problem formulation" a method subsection, ...).
GENERIC_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?:^|\s)ablation"), "experiments"),
    (re.compile(r"(?:^|\s)benchmark"), "experiments"),
    (re.compile(r"real robot"), "experiments"),
    (re.compile(r"(?:^|\s)implementation details"), "method"),
    (re.compile(r"problem formulation"), "method"),
    (re.compile(r"fine[- ]?tuning"), "method"),
    (re.compile(r"meta[- ]?learning"), "method"),
    (re.compile(r"^algorithms?\s+for"), "method"),
    (re.compile(r"main results"), "results"),
]

NUMBER_PREFIX = re.compile(
    r"^\s*(?:(?:section\s+)?(?:\d+(?:\.\d+){0,3}|[ivxlcdm]+|[A-Z])(?:[.)])?\s+)",
    re.IGNORECASE,
)
TRAILING_PUNCT = re.compile(r"[.:：。]\s*$")
# A paragraph line that continues mid-sentence ("...Benchmark. We evaluate ...")
# is body text, not a heading.
INNER_SENTENCE = re.compile(r"\.\s+[A-Z]")
# Generic English sentence openers: an unnumbered heading rarely starts with these.
SENTENCE_STARTERS = {
    "the", "a", "an", "we", "our", "this", "these", "that", "those", "in", "for",
    "however", "moreover", "while", "as", "then", "there", "it", "its", "their",
    "here", "also", "although", "since", "because", "first", "second", "third",
    "finally", "on", "at", "with", "from", "after", "before", "note",
}
MAX_PATTERN_WORDS = 7


@dataclass(frozen=True, slots=True)
class HeadingCandidate:
    block: Block
    title: str
    canonical_name: str
    level: int
    confidence: float


def _canonical_name(text: str) -> str | None:
    """Map a confirmed heading to a generic canonical section type.

    No demo-paper-specific titles live here: known headings come from the shared
    dictionary (exact or trailing-word match, e.g. "Training-free method" ends
    with "method"), and recurring ML/CV section semantics from GENERIC_PATTERNS.
    Anything else is left for the caller to classify via context or "other".
    """
    normalized = normalize_match_text(NUMBER_PREFIX.sub("", text))
    normalized = TRAILING_PUNCT.sub("", normalized).strip()
    for canonical, aliases in CANONICAL_TITLES.items():
        if normalized in aliases:
            return canonical
    words = normalized.split()
    for canonical, aliases in CANONICAL_TITLES.items():
        if words and len(words) <= 5 and words[-1] in aliases:
            return canonical
    for pattern, canonical in GENERIC_PATTERNS:
        if pattern.search(normalized):
            return canonical
    return None


def _heading_title(text: str) -> str:
    """Strip a tiny formula fragment that sometimes precedes a numbered heading."""

    clean = text.strip()
    if NUMBER_PREFIX.match(clean):
        return clean
    embedded = re.match(
        r"^[a-zα-ω](?:\s|\s*[-=+]\s*)+"
        r"(?P<title>(?:\d+(?:\.\d+){0,3}|[A-Z])(?:[.)])?\s+.+)$",
        clean,
    )
    return embedded.group("title") if embedded else clean


def _canonical_prefix(text: str) -> str | None:
    normalized = normalize_match_text(NUMBER_PREFIX.sub("", text))
    for canonical, aliases in CANONICAL_TITLES.items():
        if any(
            normalized.startswith(alias + " ") and len(normalized.split()) <= 7 for alias in aliases
        ):
            return canonical
    return None


def _heading_level(text: str) -> int:
    match = re.match(r"^\s*(\d+(?:\.\d+){0,3})", text)
    if match:
        return min(4, match.group(1).count(".") + 1)
    if re.match(r"^\s*[A-Z][.)]?\s+", text):
        return 1
    return 1


def heading_candidate(block: Block, body_font: float | None = None) -> HeadingCandidate | None:
    if block.block_type != BlockType.TEXT:
        return None
    text = _heading_title(block.text)
    if not text or len(text) > 120 or len(text.split()) > 14:
        return None
    # A line starting with a lowercase letter + space is body text, never a
    # heading (the letter-prefix alternative of NUMBER_PREFIX is case-folded).
    if re.match(r"^[a-z]\s", text):
        return None
    numbered = bool(NUMBER_PREFIX.match(text))
    # "0.0001. A learning rate ..." is a body sentence starting with a decimal
    # value, not a section number like "1.2".
    if numbered and re.match(r"^\s*0\.\d", text):
        numbered = False
    body_size = block.metadata.get("body_font_size") or body_font
    larger = bool(
        block.font_size
        and body_size
        and block.font_size >= max(float(body_size) * 1.08, 8.5)
    )
    canonical = _canonical_name(text)
    if canonical is None and numbered:
        canonical = _canonical_prefix(text)
    # Avoid sentences/captions that happen to start with a keyword.
    if text.endswith(("?", "!", ",", ";")) or re.match(
        r"^(figure|fig\.?|table|tab\.?)\s+\w+\d", text, re.I
    ):
        return None
    if not numbered and text.endswith((".", "。")):
        return None
    # Body lines that continue a sentence ("...Benchmark. We evaluate ...") are
    # not headings, even when a keyword appears inside them. The numbering
    # prefix ("1. Introduction") is stripped first so its own ". " is ignored.
    if INNER_SENTENCE.search(NUMBER_PREFIX.sub("", text, count=1)):
        return None
    if not numbered:
        words = normalize_match_text(text).split()
        if words and words[0] in SENTENCE_STARTERS:
            return None
        if not text[0].isupper():
            return None
        if canonical is None and len(text.split()) > MAX_PATTERN_WORDS:
            return None
    # canonical may still be None here for a styled/numbered line that the
    # dictionary and generic patterns cannot classify; detect_sections resolves
    # it through parent-context inheritance or falls back to "other".
    if canonical is None:
        if not numbered:
            return None
        stripped = NUMBER_PREFIX.sub("", text, count=1).strip()
        if not stripped or len(stripped) < 4 or not stripped[0].isupper():
            return None
        if "://" in stripped or "=" in stripped or any(sym in stripped for sym in "∈∑⊂∪∩"):
            return None
        tokens = stripped.split()
        numeric = sum(
            1
            for token in tokens
            if token.replace(".", "").replace(",", "").replace("%", "").isdigit()
        )
        digit_ratio = numeric / max(len(tokens), 1)
        if digit_ratio >= 0.4:
            return None
        if re.search(r"\b(?:19|20)\d{2}[a-z]?\.?\s*$", stripped):
            return None
        if re.match(r"^[A-Z]", text) and re.match(r"^[A-Z][.)]\s*\S+:", text):
            return None
    normalized = normalize_match_text(text)
    unstyled_allowed = canonical == "abstract" or normalized in {
        "references",
        "bibliography",
        "参考文献",
    }
    if not unstyled_allowed and not (numbered or larger):
        return None
    score = 0.48
    score += 0.18 if numbered else 0
    score += 0.18 if larger else 0
    score += 0.12 if block.is_bold else 0
    if canonical in {"abstract", "references", "appendix"}:
        score += 0.08
    return HeadingCandidate(
        block=block,
        title=text,
        canonical_name=canonical,
        level=_heading_level(text),
        confidence=min(score, 0.99),
    )


def detect_sections(paper_id: str, blocks: list[Block]) -> tuple[list[Section], list[Block]]:
    """Detect section headings and assign every block to its nearest preceding section."""

    ordered = sorted(blocks, key=lambda block: (block.page, block.block_index))
    media = [block for block in ordered if block.block_type in {BlockType.TABLE, BlockType.FIGURE}]

    def inside_media(candidate: HeadingCandidate) -> bool:
        x0, top, x1, bottom = candidate.block.bbox
        center_x, center_y = (x0 + x1) / 2, (top + bottom) / 2
        return any(
            object_block.page == candidate.block.page
            and object_block.bbox[0] <= center_x <= object_block.bbox[2]
            and object_block.bbox[1] <= center_y <= object_block.bbox[3]
            for object_block in media
        )

    from collections import Counter

    # 审计 P1（2026-08-05）：纯图片/仅媒体 PDF 可能没有带 font_size 的
    # TEXT 块——空 Counter 直接 [0][0] 会 IndexError 崩溃
    font_counts = Counter(
        round(block.font_size, 1)
        for block in ordered
        if block.block_type == BlockType.TEXT and block.font_size
    )
    body_font = font_counts.most_common(1)[0][0] if font_counts else None
    candidates = [
        candidate
        for block in ordered
        if (candidate := heading_candidate(block, body_font)) and not inside_media(candidate)
    ]
    # Context inheritance: an unknown numbered subsection under a known parent
    # ("2.2 Region Propagation Network" under "2 Method") takes the parent's
    # canonical type. This is a structural rule, not a title dictionary. An
    # ancestor stack handles same-level siblings ("2.2" after "2.1").
    known_stack: list[tuple[str, int]] = []
    sections: list[Section] = []
    for index, candidate in enumerate(candidates):
        canonical = candidate.canonical_name
        if canonical is None:
            while known_stack and known_stack[-1][1] >= candidate.level:
                known_stack.pop()
            if known_stack:
                canonical = known_stack[-1][0]
            else:
                canonical = "other"
        else:
            while known_stack and known_stack[-1][1] >= candidate.level:
                known_stack.pop()
            known_stack.append((canonical, candidate.level))
        next_page = candidates[index + 1].block.page if index + 1 < len(candidates) else None
        section_id = f"sec-{paper_id}-{index:03d}-{sha256_text(candidate.block.text)[:6]}"
        sections.append(
            Section(
                section_id=section_id,
                # V4.1：DocumentGraph 统一——Section 用 paper_version_id
                #（解析阶段可为空串，to_sections 以 version 补全）
                paper_version_id=blocks[0].paper_version_id if blocks else "",
                title=candidate.title,
                canonical_name=canonical,
                level=candidate.level,
                start_page=candidate.block.page,
                end_page=(
                    next_page if next_page is None else max(candidate.block.page, next_page - 1)
                ),
                confidence=candidate.confidence,
                heading_block_id=candidate.block.block_id,
            )
        )

    # Reference-list entries masquerade as letter-numbered "headings"
    # ("E. Lightsam: ..."). They live inside the References span: drop any
    # unclassified "other" section that starts inside it (before the appendix).
    references = next(
        (section for section in sections if section.canonical_name == "references"), None
    )
    appendix = next(
        (section for section in sections if section.canonical_name == "appendix"), None
    )
    if references is not None:
        clean: list[Section] = []
        for section in sections:
            inside_references = (
                section.start_page >= references.start_page
                and (appendix is None or section.start_page < appendix.start_page)
            )
            if section.canonical_name == "other" and inside_references:
                continue
            clean.append(section)
        sections = clean

    heading_map = {section.heading_block_id: section for section in sections}
    current: Section | None = None
    stack: list[Section] = []
    assigned: list[Block] = []
    for block in ordered:
        if block.block_id in heading_map:
            current = heading_map[block.block_id]
            while stack and stack[-1].level >= current.level:
                stack.pop()
            stack.append(current)
        path = " > ".join(section.title for section in stack) if stack else "Front matter"
        assigned.append(
            block.model_copy(
                update={"section_id": current.section_id if current else None, "section_path": path}
            )
        )
    return sections, assigned


def section_metrics(
    predicted: list[Section], gold: list[dict[str, object]]
) -> dict[str, float | int | None]:
    """Report canonical/page F1 plus title detection and hierarchy diagnostics.

    Diagnostics beyond the set-based F1 (which hides duplicate detections):
    ``duplicate_heading_false_positives`` counts repeated (canonical, page) pairs,
    and ``order_accuracy`` measures whether predicted section order matches gold.
    """

    predicted_pairs = {
        (section.canonical_name, section.start_page)
        for section in predicted
        if section.canonical_name != "acknowledgements"
    }
    gold_pairs = {(str(item["canonical_name"]), int(item["start_page"])) for item in gold}
    # True duplicate false positives: the same heading title detected more than
    # once. Same-page sections with different titles (e.g. "3. Method" and
    # "3.2 Training-free method" both starting on page 5) are NOT duplicates.
    seen_titles: dict[str, int] = {}
    duplicates: list[str] = []
    for section in predicted:
        if section.canonical_name == "acknowledgements":
            continue
        title = normalize_match_text(section.title)
        if title in seen_titles:
            duplicates.append(f"{title}@{section.start_page}")
        seen_titles.setdefault(title, section.start_page)
    gold_order = [(str(item["canonical_name"]), int(item["start_page"])) for item in gold]
    predicted_order = [
        (section.canonical_name, section.start_page)
        for section in predicted
        if section.canonical_name != "acknowledgements"
    ]
    order_correct = sum(
        1
        for index, gold_key in enumerate(gold_order)
        if index < len(predicted_order) and predicted_order[index] == gold_key
    )
    order_accuracy = order_correct / len(gold_order) if gold_order else None
    true_positive = len(predicted_pairs & gold_pairs)
    precision = true_positive / len(predicted_pairs) if predicted_pairs else 0.0
    recall = true_positive / len(gold_pairs) if gold_pairs else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    has_titles = all("raw_title" in item for item in gold)
    heading_precision: float | None = None
    heading_recall: float | None = None
    heading_f1: float | None = None
    mapping_accuracy: float | None = None
    hierarchy_accuracy: float | None = None
    if has_titles:
        predicted_by_heading = {
            (normalize_match_text(section.title), section.start_page): section
            for section in predicted
            if section.canonical_name != "acknowledgements"
        }
        gold_by_heading = {
            (normalize_match_text(str(item["raw_title"])), int(item["start_page"])): item
            for item in gold
        }
        detected_keys = predicted_by_heading.keys() & gold_by_heading.keys()
        predicted_count = len(predicted_by_heading)
        heading_precision = len(detected_keys) / predicted_count if predicted_count else 0.0
        heading_recall = len(detected_keys) / len(gold_by_heading) if gold_by_heading else 0.0
        heading_f1 = (
            2 * heading_precision * heading_recall / (heading_precision + heading_recall)
            if heading_precision + heading_recall
            else 0.0
        )
        mapping_correct = sum(
            predicted_by_heading[key].canonical_name == str(gold_by_heading[key]["canonical_name"])
            for key in detected_keys
        )
        mapping_accuracy = mapping_correct / len(detected_keys) if detected_keys else 0.0
        hierarchy_keys = [key for key in detected_keys if "level" in gold_by_heading[key]]
        hierarchy_correct = sum(
            predicted_by_heading[key].level == int(gold_by_heading[key]["level"])
            for key in hierarchy_keys
        )
        hierarchy_accuracy = (
            hierarchy_correct / len(hierarchy_keys) if hierarchy_keys else None
        )
    return {
        "true_positive": true_positive,
        "predicted": len(predicted_pairs),
        "gold": len(gold_pairs),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "duplicate_heading_false_positives": len(duplicates),
        "duplicate_headings": duplicates,
        "order_accuracy": round(order_accuracy, 4) if order_accuracy is not None else None,
        "heading_detection_precision": (
            round(heading_precision, 4) if heading_precision is not None else None
        ),
        "heading_detection_recall": (
            round(heading_recall, 4) if heading_recall is not None else None
        ),
        "heading_detection_f1": round(heading_f1, 4) if heading_f1 is not None else None,
        "canonical_mapping_accuracy": (
            round(mapping_accuracy, 4) if mapping_accuracy is not None else None
        ),
        "hierarchy_accuracy": (
            round(hierarchy_accuracy, 4) if hierarchy_accuracy is not None else None
        ),
    }
