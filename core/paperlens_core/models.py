"""Typed domain models shared by deterministic and LLM-assisted modules.

V4.1（改进方案3 §3.2/§五）：DocumentGraph 统一——documents.py 是唯一事实源，
重复实体（Block/BlockType/Chunk/ChunkSegment/Section/ParseStatus/
ReferenceIdentity/StrEnum）在此 re-export，legacy 消费者无需改动。
本文件保留两类专属模型：解析输出元信息（Paper，V4.2 演进为 ParseRun）与
QA/证据内核模型（AnswerDraft/EvidenceItem/...）。
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone as _tz

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .documents import (
    Block,
    BlockType,
    Chunk,
    ChunkSegment,
    ParseStatus,
    ReferenceIdentity,
    Section,
    StrEnum,
)


def utc_now_iso() -> str:
    return datetime.now(_tz.utc).isoformat(timespec="seconds")


class Paper(BaseModel):
    """解析输出元信息（与 documents.Paper 库行实体语义不同；
    V4.2 起 ParseRun 承载运行信息，Paper 保留静态元数据）。"""

    paper_id: str
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    file_name: str
    file_sha256: str
    page_count: int = 0
    language: str = "unknown"
    parser_name: str = "pdfplumber"
    parser_version: str = "unknown"
    parse_status: ParseStatus = ParseStatus.READY
    created_at: str = Field(default_factory=utc_now_iso)


class ParseRun(BaseModel):
    """V4.2（改进方案3 §五/§十七）：一次解析运行的可追溯记录。

    记录实际使用的解析管线、页级质量与 Active Quality Gate 的融合决策，
    随版本持久化（documents kind="parse_run"）。
    """

    parse_run_id: str
    paper_version_id: str
    parser_pipeline: str = ""  # 例如 "hybrid:pymupdf"
    engine: str = ""           # 实际主引擎
    page_count: int = 0
    quality_summary: dict[str, int] = Field(default_factory=dict)  # GOOD/SUSPECT/LOW 计数
    fused_pages: dict[str, str] = Field(default_factory=dict)      # page -> 采用的引擎
    started_at: str = Field(default_factory=utc_now_iso)
    finished_at: str = ""


class SearchHit(BaseModel):
    chunk: Chunk
    lexical_score: float = 0.0
    dense_score: float | None = None
    rrf_score: float = 0.0
    rank: int = 0


class ClaimType(StrEnum):
    AUTHOR_CLAIM = "AUTHOR_CLAIM"
    OBSERVED_RESULT = "OBSERVED_RESULT"
    AUTHOR_LIMITATION = "AUTHOR_LIMITATION"
    AGENT_INFERENCE = "AGENT_INFERENCE"
    AGENT_CRITIQUE = "AGENT_CRITIQUE"


class SupportStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    CONTRADICTED = "CONTRADICTED"
    NOT_FOUND = "NOT_FOUND"


class EvidenceItem(BaseModel):
    evidence_id: str
    question_id: str
    paper_id: str
    chunk_id: str
    block_ids: list[str]
    verbatim_excerpt: str
    page_start: int
    page_end: int
    section_path: str
    lexical_score: float = 0.0
    dense_score: float | None = None
    rrf_score: float = 0.0
    claim_type: ClaimType = ClaimType.AUTHOR_CLAIM
    segments: list[dict[str, object]] = Field(default_factory=list)  # ChunkSegment dumps


class EvidenceLink(BaseModel):
    """Claim-specific attribution to a literal span inside one evidence item."""

    evidence_id: str
    verbatim_quote: str = Field(min_length=1, max_length=1200)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    quote_sha256: str = ""
    support_status: SupportStatus | None = None
    # precise reverse location (改进方案2.md §16.1): block + block char range +
    # page + physical bboxes, filled by EvidenceGuard after quote validation
    locators: list[dict[str, object]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_span(self) -> EvidenceLink:
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        return self


class AnswerClaim(BaseModel):
    claim_id: str
    text: str
    evidence_links: list[EvidenceLink] = Field(default_factory=list, min_length=1, max_length=5)
    # V3.16: claim_type 移出输出 schema——全链路无消费者（前端流式事件
    # 硬编码 AUTHOR_CLAIM），少一个字段 = 少一段生成 token


class CoverageStatus(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND_IN_SEARCHED_SECTIONS = "NOT_FOUND_IN_SEARCHED_SECTIONS"
    NOT_REPORTED_CONFIRMED = "NOT_REPORTED_CONFIRMED"
    UNASSESSABLE_PARSE_GAP = "UNASSESSABLE_PARSE_GAP"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CoverageNote(BaseModel):
    status: CoverageStatus
    checked_sections: list[str] = Field(default_factory=list)
    note: str = Field(max_length=800)


class AnswerDraft(BaseModel):
    claims: list[AnswerClaim]
    answer_summary_claim_ids: list[str] = Field(default_factory=list)
    # V3.16: coverage_notes 移出 draft 输出——前端无展示，finalize 填空列表。
    # draft 只做"主张+引文"，压缩生成 token（实测该字段约占输出 1%）


class GroundedAnswer(BaseModel):
    answer: str
    claims: list[AnswerClaim]
    coverage_notes: list[CoverageNote] = Field(default_factory=list)
    rejected_claims: list[dict[str, Any]] = Field(default_factory=list)


class QualityDimension(BaseModel):
    name: str
    score: int = Field(ge=0, le=4)
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str
    missing_information: list[str] = Field(default_factory=list)


class QualityAssessment(BaseModel):
    dimensions: list[QualityDimension]
    weighted_score: float | None = None
    evidence_coverage: float = Field(default=0.0, ge=0, le=1)
    summary: str = ""
    caveats: list[str] = Field(default_factory=list)


class ReferenceRecord(BaseModel):
    reference_id: str
    raw_text: str
    sequence_number: int | None = None
    parsed_title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""
    arxiv_id: str = ""
    pmid: str = ""
    format_issues: list[str] = Field(default_factory=list)
    identity_status: ReferenceIdentity = ReferenceIdentity.UNRESOLVED
    identifier_resolution: Literal[
        "RESOLVES", "NOT_FOUND", "ERROR", "UNSUPPORTED_RA", "NOT_CHECKED"
    ] = "NOT_CHECKED"
    record_match: Literal["EXACT", "HIGH_CONFIDENCE", "AMBIGUOUS", "MISMATCH", "NOT_CHECKED"] = (
        "NOT_CHECKED"
    )
    provider_evidence: list[dict[str, Any]] = Field(default_factory=list)


class CleaningEvent(BaseModel):
    paper_id: str
    event_type: str
    page: int | None = None
    detail: str
    count: int = 1
    created_at: str = Field(default_factory=utc_now_iso)


class IngestResult(BaseModel):
    paper: Paper
    blocks: list[Block]
    sections: list[Section]
    chunks: list[Chunk]
    cleaning_events: list[CleaningEvent]

    @model_validator(mode="after")
    def ensure_same_paper(self) -> IngestResult:
        ids = {self.paper.paper_id}
        ids.update(block.paper_id for block in self.blocks)
        ids.update(section.paper_id for section in self.sections)
        ids.update(chunk.paper_id for chunk in self.chunks)
        if len(ids) != 1:
            raise ValueError("ingest result contains records from different papers")
        return self
