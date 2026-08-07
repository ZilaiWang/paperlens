"""Deterministic reference-section parsing and IEEE numeric style checks.

This module deliberately limits itself to bibliographic *structure*.  It does not
claim that a cited work supports the surrounding prose; that requires access to
the cited work's full text and a separate claim-evidence audit.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from paperlens_core.models import ReferenceRecord

REFERENCE_HEADING_RE = re.compile(
    r"(?im)^\s*(?:(?:\d+(?:\.\d+)*)\s+)?(?:references|bibliography|参考文献)\s*$"
)
STOP_HEADING_RE = re.compile(
    r"(?im)^\s*(?:(?:\d+(?:\.\d+)*)\s+)?"
    r"(?:appendix|appendices|supplement(?:ary material)?|acknowledg(?:e)?ments?|"
    r"author biographies|附录|致谢)\s*$"
)
NUMERIC_ENTRY_RE = re.compile(r"(?m)^\s*(?:\[(?P<bracket>\d{1,4})\]|(?P<plain>\d{1,4})[.)])\s+")
NUMERIC_PREFIX_RE = re.compile(r"^\s*(?:\[(?P<bracket>\d{1,4})\]|(?P<plain>\d{1,4})[.)])\s+")
# 年份不得后跟 ".数字"——arXiv 编号(1904.04232)与 DOI(10.48550/arXiv.2411.00001)
# 里的 4 位数字会被误抓成 19xx/20xx 年份(修复 2026-08-05)
YEAR_RE = re.compile(r"(?<!\d)(?P<year>(?:18|19|20)\d{2})(?!\d|\.\d)")
DOI_RE = re.compile(r"(?i)\b10\.\d{4,9}/[-._;()/:A-Z0-9]+")
DOI_HINT_RE = re.compile(r"(?i)(?:\bdoi\s*:|https?://(?:dx\.)?doi\.org/|\b10\.\d{4,9}/)")
ARXIV_RE = re.compile(
    r"(?ix)\b(?:arxiv\s*:\s*)?"
    r"(?P<identifier>(?:\d{4}\.\d{4,5}|[a-z][a-z0-9.+-]*(?:\.[A-Z]{2})?/\d{7})"
    r"(?:v\d+)?)\b"
)
ARXIV_EXPLICIT_RE = re.compile(
    r"(?ix)\barxiv(?:\s+preprint)?\s*:?\s*"
    r"(?P<identifier>(?:\d{4}\.\d{4,5}|[a-z][a-z0-9.+-]*(?:\.[A-Z]{2})?/\d{7})"
    r"(?:v\d+)?)\b"
)
LEGACY_ARXIV_RE = re.compile(
    r"(?ix)\b(?P<identifier>[a-z][a-z0-9.+-]*(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)\b"
)
ARXIV_HINT_RE = re.compile(r"(?i)\barxiv\b")
QUOTED_TITLE_RE = re.compile(r"[\"“”](?P<title>.+?)[\"“”]")


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_reference_section(text: str) -> str:
    """Return the text following a References/Bibliography heading.

    When no heading is present, ``text`` is returned unchanged.  This makes the
    function useful both with a whole-document extraction and with an already
    isolated reference section.
    """

    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    heading = REFERENCE_HEADING_RE.search(normalized)
    section_start = heading.end() if heading else 0
    section = normalized[section_start:]
    stop = STOP_HEADING_RE.search(section)
    if stop:
        section = section[: stop.start()]
    return section.strip()


def split_reference_entries(text: str) -> list[str]:
    """Split a reference section with deterministic numeric/paragraph rules.

    IEEE bracketed numbering is preferred.  ``1.`` and ``1)`` are accepted as a
    recoverable input form so the linter can later report that it is not IEEE.
    Continuation lines are joined to their preceding entry.
    """

    section = extract_reference_section(text)
    if not section:
        return []

    matches = list(NUMERIC_ENTRY_RE.finditer(section))
    if matches:
        entries: list[str] = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
            entry = _collapse_whitespace(section[match.start() : end])
            if entry:
                entries.append(entry)
        return entries

    paragraphs = [
        _collapse_whitespace(part)
        for part in re.split(r"\n\s*\n+", section)
        if _collapse_whitespace(part)
    ]
    if len(paragraphs) > 1:
        return paragraphs

    # Last-resort rule for unnumbered extractions with one reference per line.
    lines = [_collapse_whitespace(line) for line in section.splitlines() if line.strip()]
    return lines if len(lines) > 1 else paragraphs


def _trim_unbalanced_closers(value: str) -> str:
    pairs = (("(", ")"), ("[", "]"), ("{", "}"))
    for opener, closer in pairs:
        while value.endswith(closer) and value.count(closer) > value.count(opener):
            value = value[:-1]
    return value


def normalize_doi(value: str) -> str:
    """Normalize a DOI or DOI URL without guessing malformed identifiers."""

    normalized = value.strip()
    normalized = re.sub(r"(?i)^https?://(?:dx\.)?doi\.org/", "", normalized)
    normalized = re.sub(r"(?i)^doi\s*:\s*", "", normalized)
    normalized = _trim_unbalanced_closers(normalized.rstrip(".,;:"))
    match = DOI_RE.fullmatch(normalized)
    return normalized.lower() if match else ""


def extract_doi(text: str) -> str:
    """Extract the first syntactically valid DOI from text."""

    if not text:
        return ""
    match = DOI_RE.search(text)
    return normalize_doi(match.group(0)) if match else ""


def normalize_arxiv_id(value: str) -> str:
    normalized = re.sub(r"(?i)^https?://arxiv\.org/(?:abs|pdf)/", "", value.strip())
    normalized = normalized.rstrip(".,;:)]}")
    normalized = re.sub(r"(?i)\.pdf$", "", normalized)
    normalized = re.sub(r"(?i)^arxiv\s*:\s*", "", normalized)
    match = ARXIV_RE.fullmatch(normalized)
    return match.group("identifier").lower() if match else ""


def extract_arxiv_id(text: str) -> str:
    """Extract a modern or legacy arXiv identifier, preserving its version."""

    if not text:
        return ""
    url_match = re.search(r"(?i)https?://arxiv\.org/(?:abs|pdf)/([^\s?#]+)", text)
    if url_match:
        normalized = normalize_arxiv_id(url_match.group(1))
        if normalized:
            return normalized
    explicit = ARXIV_EXPLICIT_RE.search(text)
    if explicit:
        return explicit.group("identifier").lower()
    # BibTeX style "CoRR, abs/1409.0473, 2014." — the abs/ prefix marks the id
    # as strongly as an explicit "arXiv:" token, without a false-positive risk
    abs_match = re.search(
        r"(?i)\babs/(?P<identifier>(?:\d{4}\.\d{4,5}|[a-z][a-z0-9.+-]*(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)\b",
        text,
    )
    if abs_match:
        return abs_match.group("identifier").lower()
    legacy = LEGACY_ARXIV_RE.search(text)
    if legacy:
        return legacy.group("identifier").lower()
    # Accept a bare identifier only when the entire value is the identifier;
    # this avoids treating DOI suffixes such as ``.../2401.01234`` as arXiv IDs.
    return normalize_arxiv_id(text)


def _split_authors(author_text: str) -> list[str]:
    cleaned = author_text.strip(" ,.;")
    if not cleaned:
        return []
    parts = re.split(r",\s+(?=(?:and\s+)?[A-ZÀ-Þ])|\s+(?:and|&)\s+", cleaned)
    authors = [re.sub(r"(?i)^and\s+", "", part).strip(" ,.;") for part in parts]
    return [author for author in authors if author]


def _heuristic_title(body: str, year_match: re.Match[str] | None) -> str:
    quoted = QUOTED_TITLE_RE.search(body)
    if quoted:
        return quoted.group("title").strip(" ,.;")

    before_year = body[: year_match.start()] if year_match else body

    # ① 作者列表以 "and <末作者>." 收尾（IEEE 常见）——标题即末作者
    # 句点后第一个 ≥2 词段。缩写句点（"A. Farhadi"）会被 1 词候选滤掉
    if m := re.search(r"(?i)\band\s+[A-ZÀ-Þ]", before_year):
        after = before_year[m.end():]
        for em in re.finditer(r"\.\s+(?=[A-ZÀ-Þ])", after):
            candidate = after[em.end():].split(". ")[0].strip(" ,.;")
            if len(candidate.split()) >= 2 and "arxiv" not in candidate.lower():
                return candidate

    # ② "et al." 收尾——标题紧跟在标记之后
    if m := re.search(r"(?i)\bet\s+al\.\s+", before_year):
        candidate = before_year[m.end():].split(". ")[0].strip(" ,.;")
        if len(candidate.split()) >= 2 and "arxiv" not in candidate.lower():
            return candidate

    segments = [segment.strip(" ,.;") for segment in before_year.split(",")]
    # ③ 常规 IEEE：段 0 作者、段 1 标题；但段 1 若以名缩写开头
    #（"S. Divvala"）则仍是作者，跳到 ④
    if (
        len(segments) >= 2
        and len(segments[1].split()) >= 2
        and not re.match(r"^[A-ZÀ-Þ]\.\s", segments[1])
    ):
        return segments[1]
    # ④ 回退：按句点切语义段，取作者段后的第一个非 venue 段
    #（顺带兼容 "John Smith. A great paper. Journal of Science,"）
    sentences = [s.strip(" ,.;") for s in before_year.split(".")]
    for sentence in sentences[1:]:
        lowered = sentence.lower()
        if len(sentence.split()) < 2:
            continue
        if "arxiv" in lowered or "preprint" in lowered or "http" in lowered:
            continue
        if re.fullmatch(r"[\d.,\s-]+", sentence):
            continue
        return sentence
    return ""


def parse_reference_entry(raw_text: str, *, fallback_index: int = 1) -> ReferenceRecord:
    """Extract conservative local fields from one reference entry."""

    raw = _collapse_whitespace(raw_text)
    prefix = NUMERIC_PREFIX_RE.match(raw)
    sequence_number: int | None = None
    body = raw
    if prefix:
        sequence_number = int(prefix.group("bracket") or prefix.group("plain"))
        body = raw[prefix.end() :].strip()

    year_match = YEAR_RE.search(body)
    year = int(year_match.group("year")) if year_match else None
    quoted = QUOTED_TITLE_RE.search(body)
    title = _heuristic_title(body, year_match)
    # 作者段截止于标题开始处（无引号时由启发式给出标题位置）——
    # 修复无逗号条目把标题/venue 全吞进作者的问题
    if quoted:
        author_end = quoted.start()
    elif title:
        author_end = body.find(title)
    else:
        author_end = body.find(",")
    author_text = body[:author_end] if author_end >= 0 else ""
    authors = _split_authors(author_text)

    venue = ""
    if quoted:
        venue_tail = body[quoted.end() :]
        if year_match and year_match.start() > quoted.end():
            venue_tail = body[quoted.end() : year_match.start()]
        venue = venue_tail.strip(" ,.;")

    return ReferenceRecord(
        reference_id=f"ref-{fallback_index:04d}",
        raw_text=raw,
        sequence_number=sequence_number,
        parsed_title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=extract_doi(body),
        arxiv_id=extract_arxiv_id(body),
    )


def parse_references(text: str) -> list[ReferenceRecord]:
    """Split, parse, and lint a References section."""

    records = [
        parse_reference_entry(entry, fallback_index=index)
        for index, entry in enumerate(split_reference_entries(text), start=1)
    ]
    return lint_references(records)


def _append_issue(issues: list[str], issue: str) -> None:
    if issue not in issues:
        issues.append(issue)


def _current_year() -> int:
    from datetime import date

    return date.today().year


def lint_references(records: Iterable[ReferenceRecord]) -> list[ReferenceRecord]:
    """Return copies of records annotated with conservative format issues.

    V4.8（题目要求③）：风格感知——数字引用（IEEE 式 [n]）与作者-年份式
    （Smith, 2016）分别检查；公共检查覆盖 作者/标题/年份/DOI/arXiv/
    末尾句号/年份合理性。
    """

    materialized = list(records)
    has_numeric = [record.sequence_number is not None for record in materialized]
    style = (
        "numeric"
        if has_numeric and all(has_numeric)
        else "author_year"
        if has_numeric and not any(has_numeric)
        else "mixed"
    )
    seen_numbers: set[int] = set()
    output: list[ReferenceRecord] = []

    for expected, record in enumerate(materialized, start=1):
        issues = list(record.format_issues)
        if style == "mixed":
            _append_issue(issues, "REF_MIXED_STYLE")
        if style in ("numeric", "mixed"):
            prefix = NUMERIC_PREFIX_RE.match(record.raw_text)
            if record.sequence_number is None:
                _append_issue(issues, "REF_MISSING_NUMBER")
            else:
                if record.sequence_number in seen_numbers:
                    _append_issue(issues, "REF_DUPLICATE_NUMBER")
                seen_numbers.add(record.sequence_number)
                if record.sequence_number != expected:
                    _append_issue(issues, "REF_NON_SEQUENTIAL_NUMBER")
                # 仅当 raw 里存在可见的数字标签且非 [n] 形式才算违规；
                # HTML 路径（arxiv_html.parse_bibliography）有意剥离了
                # 双重序号前缀，raw 无前缀是正常状态，不应报 REF_NON_IEEE_NUMBER
                if prefix and prefix.group("bracket") is None:
                    _append_issue(issues, "REF_NON_IEEE_NUMBER")

        if not record.authors:
            _append_issue(issues, "REF_MISSING_AUTHOR")
        if not record.parsed_title:
            _append_issue(issues, "REF_MISSING_TITLE")
        elif len(record.parsed_title.strip()) < 8:
            _append_issue(issues, "REF_TITLE_TOO_SHORT")
        if record.year is None:
            _append_issue(issues, "REF_MISSING_YEAR")
        else:
            year = int(record.year)
            if year < 1900 or year > _current_year() + 1:
                _append_issue(issues, f"REF_IMPLAUSIBLE_YEAR:{year}")
        if not record.raw_text.rstrip().endswith("."):
            _append_issue(issues, "REF_MISSING_FINAL_PERIOD")
        if DOI_HINT_RE.search(record.raw_text) and not record.doi:
            _append_issue(issues, "REF_BAD_DOI")
        if ARXIV_HINT_RE.search(record.raw_text) and not record.arxiv_id:
            _append_issue(issues, "REF_BAD_ARXIV_ID")

        output.append(record.model_copy(update={"format_issues": issues}))
    return output


lint_ieee_numeric = lint_references  # 兼容别名（V4.8 更名）


class ReferenceParser:
    """Small class facade for dependency injection in the application workflow."""

    split_entries = staticmethod(split_reference_entries)
    parse_entry = staticmethod(parse_reference_entry)
    parse = staticmethod(parse_references)


class FormatLinter:
    """IEEE numeric format linter facade."""

    lint = staticmethod(lint_references)


__all__ = [
    "FormatLinter",
    "ReferenceParser",
    "extract_arxiv_id",
    "extract_doi",
    "extract_reference_section",
    "lint_ieee_numeric",
    "lint_references",
    "normalize_arxiv_id",
    "normalize_doi",
    "parse_reference_entry",
    "parse_references",
    "serialize_reference_records",
    "split_reference_entries",
]

def serialize_reference_records(records: list, version_id: str) -> list[dict[str, object]]:
    """V4.2：ReferenceRecord → 前端/端点兼容的字典形状（导入期持久化用，
    与 /api/papers/{id}/references 的返回保持一致，避免两处漂移）。"""
    return [
        {
            "reference_id": f"ref-{version_id[:10]}-{record.sequence_number}",
            "sequence_number": record.sequence_number,
            "raw_text": record.raw_text,
            "parsed_title": record.parsed_title,
            "authors": record.authors,
            "year": record.year,
            "venue": record.venue,
            "doi": record.doi,
            "arxiv_id": record.arxiv_id,
            "format_issues": record.format_issues,
            "identity_status": record.identity_status.value,
        }
        for record in records
    ]
