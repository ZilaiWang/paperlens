"""DocumentIR entities and stable source identities.

Block is the basis for display and positioning; Chunk is only a retrieval
derivative and never the document itself.

Stable identity: block_id = sha256(paper_version_sha + page + bbox + text_hash)
so the same logical block is addressable across re-parses and Agent citations.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrEnum(str, Enum):
    """Python 3.10 compatible StrEnum (3.11+ has it built in)."""

    def __str__(self) -> str:
        return str(self.value)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_block_id(paper_version_sha: str, page: int, bbox: tuple[float, float, float, float], text: str) -> str:
    normalized_bbox = ",".join(f"{round(value, 2)}" for value in bbox)
    payload = "|".join((paper_version_sha, str(page), normalized_bbox, sha256_text(text)))
    return "blk-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


class PaperSource(StrEnum):
    UPLOAD = "UPLOAD"
    ARXIV = "ARXIV"
    DOI = "DOI"
    URL = "URL"


class ParseStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SCANNED_OR_BROKEN = "SCANNED_OR_BROKEN"


class BlockType(StrEnum):
    # V4.1：合并 legacy models.BlockType（原含 FIGURE/TABLE 媒体类型）
    TEXT = "TEXT"
    HEADING = "HEADING"
    CAPTION = "CAPTION"
    FORMULA = "FORMULA"
    TABLE_ROW = "TABLE_ROW"
    REFERENCE_ENTRY = "REFERENCE_ENTRY"
    FIGURE = "FIGURE"
    TABLE = "TABLE"
    UNKNOWN_MEDIA = "UNKNOWN_MEDIA"


class SourceScope(StrEnum):
    FULL_TEXT = "FULL_TEXT"
    ABSTRACT_ONLY = "ABSTRACT_ONLY"
    METADATA_ONLY = "METADATA_ONLY"


class Paper(BaseModel):
    """Logical paper identity; one Paper may have several PaperVersions."""

    model_config = ConfigDict(extra="forbid")

    paper_id: str
    canonical_title: str = ""
    authors: list[str] = Field(default_factory=list)
    primary_source: PaperSource = PaperSource.UPLOAD
    user_id: str = "guest"  # 每用户配额（默认 300 篇，V3.6）
    created_at: str = ""


class PaperVersion(BaseModel):
    """One concrete artifact (arXiv v4, PMLR v119, user upload)."""

    model_config = ConfigDict(extra="forbid")

    version_id: str
    paper_id: str
    version_label: str = ""  # "v4", "PMLR v119", "upload-20260803"
    source: PaperSource = PaperSource.UPLOAD
    file_name: str = ""
    file_sha256: str = ""
    file_path: str = ""
    page_count: int = 0
    parse_status: ParseStatus = ParseStatus.READY
    created_at: str = ""


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_version_id: str
    page_number: int
    width: float = 0.0
    height: float = 0.0
    render_uri: str = ""  # served image/pdf-page URL in the cloud layout


class Block(BaseModel):
    """Smallest addressable document unit: a paragraph, heading, caption, ..."""

    model_config = ConfigDict(extra="forbid")

    block_id: str
    # V4.1：解析阶段 identity（内容哈希），存储后以 paper_version_id 为准
    paper_id: str = ""
    paper_version_id: str
    page: int
    # V4.1：legacy parser 字段（解析序索引；IR 侧以 paragraph_index 排序）
    block_index: int = 0
    section_path: str = ""
    block_type: BlockType = BlockType.TEXT
    bbox: tuple[float, float, float, float]
    text: str = ""
    font_size: float | None = None
    is_bold: bool = False
    source_scope: SourceScope = SourceScope.FULL_TEXT
    content_sha256: str = ""
    section_id: str | None = None
    paragraph_index: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str
    paper_version_id: str
    parent_id: str | None = None
    title: str = ""
    raw_title: str = ""
    canonical_name: str = "other"
    level: int = 1
    start_page: int = 0
    end_page: int | None = None
    confidence: float = 0.0
    # V4.1：legacy sections.py 字段（检测时记录标题 block）
    heading_block_id: str = ""


class SentenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_id: str
    block_id: str
    char_start: int
    char_end: int
    text: str


class AssetKind(StrEnum):
    FIGURE = "FIGURE"
    TABLE = "TABLE"
    FORMULA = "FORMULA"


class AssetSourceKind(StrEnum):
    EMBEDDED_RASTER = "EMBEDDED_RASTER"
    PAGE_CROP = "PAGE_CROP"
    VECTOR_REGION = "VECTOR_REGION"
    STRUCTURED_TABLE = "STRUCTURED_TABLE"
    FORMULA_CROP = "FORMULA_CROP"


class AssetExtractionStatus(StrEnum):
    EXTRACTED = "EXTRACTED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class Asset(BaseModel):
    """A Figure/Table/Formula as a first-class object with preview + download."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    paper_version_id: str
    asset_kind: AssetKind
    page: int
    bbox: tuple[float, float, float, float]
    caption_block_ids: list[str] = Field(default_factory=list)
    caption_original: str = ""
    caption_translation: str = ""
    content_uri: str = ""  # original image / page-crop / structured JSON
    preview_uri: str = ""
    # 服务器本地缓存文件（V3.9b）：HTML 图在导入时预下载落盘，
    # 下载/展示走本地不再回源 arXiv
    local_file: str = ""
    source_kind: AssetSourceKind = AssetSourceKind.PAGE_CROP
    structured_data: dict[str, Any] | None = None  # table cell matrix
    linked_mentions: list[str] = Field(default_factory=list)  # "Fig. 2" locations
    confidence: float = 0.0
    extraction_status: AssetExtractionStatus = AssetExtractionStatus.PARTIAL


class CitationCallout(BaseModel):
    """An in-text "[12]" / "Smith et al." bound to a Reference entry."""

    model_config = ConfigDict(extra="forbid")

    callout_id: str
    paper_version_id: str
    block_id: str
    char_start: int
    char_end: int
    raw: str
    reference_id: str | None = None


class ReferenceIdentity(StrEnum):
    VERIFIED = "VERIFIED"
    PROBABLE = "PROBABLE"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_id: str
    paper_version_id: str
    sequence_number: int = 0
    raw_text: str = ""
    parsed_title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: str = ""
    venue: str = ""
    doi: str = ""
    arxiv_id: str = ""
    format_issues: list[str] = Field(default_factory=list)
    identity_status: ReferenceIdentity = ReferenceIdentity.UNRESOLVED
    review_status: str = "UNKNOWN"  # REVIEWED / NOT_REVIEWED / UNKNOWN
    integrity_status: str = "UNKNOWN"  # NORMAL / CORRECTED / RETRACTED / UNKNOWN
    provider_evidence: list[dict[str, Any]] = Field(default_factory=list)


class TranslationStatus(StrEnum):
    PENDING = "PENDING"
    TRANSLATED = "TRANSLATED"
    NEEDS_RETRY = "NEEDS_RETRY"
    FAILED = "FAILED"


class TranslationUnit(BaseModel):
    """Source/target alignment; never overwrites the original block."""

    model_config = ConfigDict(extra="forbid")

    unit_id: str
    paper_version_id: str
    section_id: str | None = None
    source_block_ids: list[str] = Field(default_factory=list)
    source_text: str = ""
    target_text: str = ""
    source_language: str = "en"
    target_language: str = "zh"
    model: str = ""
    prompt_version: str = ""
    glossary_version: str = ""
    status: TranslationStatus = TranslationStatus.PENDING
    alignment: dict[str, Any] = Field(default_factory=dict)  # protected-token checks
    created_at: str = ""


class ChunkSegment(BaseModel):
    """Char-range mapping from chunk text back to source blocks ."""

    model_config = ConfigDict(extra="forbid")

    chunk_char_start: int
    chunk_char_end: int
    block_id: str
    block_char_start: int
    block_char_end: int
    page: int
    bboxes: list[tuple[float, float, float, float]] = Field(default_factory=list)


class Chunk(BaseModel):
    """Retrieval unit derived from Blocks. Never the document itself."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    paper_version_id: str
    # V4.1：chunking 构造期 identity（解析内容哈希）；存储后以
    # paper_version_id 为准，证据 id 也用它派生
    paper_id: str = ""
    section_id: str | None = None
    section_path: str = ""
    page_start: int = 0
    page_end: int = 0
    block_ids: list[str] = Field(default_factory=list)
    text: str = ""
    token_estimate: int = 0
    content_sha256: str = ""
    segments: list[ChunkSegment] = Field(default_factory=list)


class AnnotationKind(StrEnum):
    HIGHLIGHT = "HIGHLIGHT"
    NOTE = "NOTE"
    BOOKMARK = "BOOKMARK"
    SAVED_ANSWER = "SAVED_ANSWER"


class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annotation_id: str
    user_id: str
    paper_version_id: str
    block_id: str = ""
    char_start: int = 0
    char_end: int = 0
    kind: AnnotationKind = AnnotationKind.HIGHLIGHT
    text: str = ""
    created_at: str = ""


class AgentRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    user_id: str
    session_id: str = ""
    paper_version_id: str
    analysis_type: str = "qa"  # qa | cv_profile | quality | translation
    prompt_version: str = ""
    status: str = "RUNNING"  # RUNNING / SUCCEEDED / FAILED
    created_at: str = ""
