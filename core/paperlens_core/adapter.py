"""Adapt v1 parse output into DocumentIR entities.

The v1 pipeline (pdfplumber parse -> section rules -> chunking) stays as the
deterministic core; this adapter re-emits its output as DocumentIR objects with
stable ids, and derives Asset candidates from media placeholder blocks.
"""

from __future__ import annotations

from .documents import (
    Asset,
    AssetExtractionStatus,
    AssetKind,
    AssetSourceKind,
    Block,
    BlockType,
    Chunk,
    PaperVersion,
    Section,
    SourceScope,
    stable_block_id,
)


def legacy_block_type(legacy_type: str) -> BlockType:
    mapping = {
        "TEXT": BlockType.TEXT,
        "FORMULA": BlockType.FORMULA,
        "TABLE": BlockType.TABLE_ROW,
        "FIGURE": BlockType.UNKNOWN_MEDIA,
        "UNKNOWN_MEDIA": BlockType.UNKNOWN_MEDIA,
    }
    return mapping.get(legacy_type, BlockType.TEXT)


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def to_blocks(legacy_blocks: list, version: PaperVersion) -> list[Block]:
    blocks: list[Block] = []
    for legacy in legacy_blocks:
        text = legacy.text or ""
        if legacy.metadata.get("html_logical"):
            # HTML 逻辑块：legacy block_id 已唯一（html-{sha}-{index:05d}）；
            # 按 (page, bbox, text) 重算 stable id 会因 bbox 全 0 撞车
            # （同文本段落共享一个 id，译文 map 互相覆盖 —— fix 2026-08-04）
            block_id = legacy.block_id
        else:
            block_id = stable_block_id(version.file_sha256, legacy.page, legacy.bbox, text)
        blocks.append(
            Block(
                block_id=block_id,
                paper_version_id=version.version_id,
                page=legacy.page,
                block_type=legacy_block_type(_enum_value(legacy.block_type)),
                bbox=tuple(legacy.bbox),
                text=text,
                font_size=legacy.font_size,
                is_bold=legacy.is_bold,
                source_scope=SourceScope(_enum_value(legacy.source_scope)),
                content_sha256=legacy.content_sha256,
                section_id=legacy.section_id,
                paragraph_index=legacy.paragraph_index or 0,
                metadata=dict(legacy.metadata),
            )
        )
    return blocks


def to_sections(legacy_sections: list, version: PaperVersion) -> list[Section]:
    sections: list[Section] = []
    for legacy in legacy_sections:
        sections.append(
            Section(
                section_id=legacy.section_id,
                paper_version_id=version.version_id,
                title=legacy.title,
                raw_title=legacy.title,
                canonical_name=legacy.canonical_name,
                level=legacy.level,
                start_page=legacy.start_page,
                end_page=legacy.end_page,
                confidence=legacy.confidence,
            )
        )
    return sections


def to_chunks(legacy_chunks: list, version: PaperVersion) -> list[Chunk]:
    chunks: list[Chunk] = []
    for legacy in legacy_chunks:
        chunks.append(
            Chunk(
                chunk_id=legacy.chunk_id,
                paper_version_id=version.version_id,
                section_id=legacy.section_id,
                section_path=legacy.section_path,
                page_start=legacy.page_start,
                page_end=legacy.page_end,
                block_ids=list(legacy.block_ids),
                text=legacy.text,
                content_sha256=legacy.content_sha256,
                segments=[segment.model_dump(mode="json") for segment in legacy.segments],
            )
        )
    return chunks


def derive_assets(blocks: list[Block]) -> list[Asset]:
    """Asset candidates from media placeholder blocks: page + bbox + nearby caption.

    Consecutive TABLE_ROW blocks on the same page merge into ONE table asset
    (bbox = union) so the grid reconstructor has the whole table region
    (V3.12). Figure placeholders stay single assets.
    """
    assets: list[Asset] = []

    def add_asset(kind: AssetKind, page: int, bbox: tuple[float, float, float, float], caption: str, block_id: str) -> None:
        assets.append(
            Asset(
                asset_id=f"ast-{block_id[-16:]}",
                paper_version_id=blocks[0].paper_version_id,
                asset_kind=kind,
                page=page,
                bbox=bbox,
                caption_original=caption,
                source_kind=(
                    AssetSourceKind.STRUCTURED_TABLE
                    if kind == AssetKind.TABLE
                    else AssetSourceKind.EMBEDDED_RASTER
                ),
                extraction_status=AssetExtractionStatus.PARTIAL,
                confidence=0.5,
            )
        )

    table_start: int | None = None  # index of the first block of the open table
    for index, block in enumerate(blocks):
        if block.block_type == BlockType.TABLE_ROW:
            if table_start is None:
                table_start = index
            continue
        if block.block_type == BlockType.UNKNOWN_MEDIA:
            add_asset(AssetKind.FIGURE, block.page, tuple(block.bbox), _nearby_caption(blocks, index), block.block_id)
        if table_start is not None:
            last = blocks[index - 1]
            x0 = min(b.bbox[0] for b in blocks[table_start:index])
            y0 = min(b.bbox[1] for b in blocks[table_start:index])
            x1 = max(b.bbox[2] for b in blocks[table_start:index])
            y1 = max(b.bbox[3] for b in blocks[table_start:index])
            add_asset(
                AssetKind.TABLE,
                last.page,
                (x0, y0, x1, y1),
                _nearby_caption(blocks, table_start),
                last.block_id,
            )
            table_start = None
    if table_start is not None:
        last = blocks[-1]
        x0 = min(b.bbox[0] for b in blocks[table_start:])
        y0 = min(b.bbox[1] for b in blocks[table_start:])
        x1 = max(b.bbox[2] for b in blocks[table_start:])
        y1 = max(b.bbox[3] for b in blocks[table_start:])
        add_asset(
            AssetKind.TABLE,
            last.page,
            (x0, y0, x1, y1),
            _nearby_caption(blocks, table_start),
            last.block_id,
        )
    return assets


def _nearby_caption(blocks: list[Block], index: int) -> str:
    for offset in (1, -1, 2, -2):
        neighbor = blocks[index + offset] if 0 <= index + offset < len(blocks) else None
        if neighbor and neighbor.block_type == BlockType.TEXT and neighbor.text.strip():
            text = neighbor.text.strip()
            if len(text) <= 300:
                return text
    return ""
