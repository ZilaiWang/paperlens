"""Paragraph-first chunking that preserves source block boundaries."""

from __future__ import annotations

import re

from .models import Block, BlockType, Chunk, ChunkSegment
from .utils import estimate_tokens, normalize_space, sha256_text

HYPHEN_REPAIR_RE = re.compile(r"(?<=[A-Za-z])-\s+(?=[a-z])")


def _ends_paragraph(block: Block, next_block: Block | None) -> bool:
    if (
        next_block is None
        or block.page != next_block.page
        or block.section_id != next_block.section_id
    ):
        return True
    # arXiv HTML blocks carry no physical layout (page=1, zero bbox); each
    # LaTeXML ltx_para IS a semantic paragraph, so it always starts a new one
    if (
        block.metadata.get("html_role") == "PARAGRAPH"
        or next_block.metadata.get("html_role") == "PARAGRAPH"
    ):
        return True
    if block.block_type != BlockType.TEXT or next_block.block_type != BlockType.TEXT:
        return True
    gap = next_block.bbox[1] - block.bbox[3]
    body_size = float(block.metadata.get("body_font_size") or block.font_size or 10)
    if gap > body_size * 0.85:
        return True
    return bool(re.search(r"[.!?。！？][\]\)\"'’”]*$", block.text)) and gap > body_size * 0.35


def paragraphize(blocks: list[Block]) -> list[list[Block]]:
    ordered = sorted(blocks, key=lambda block: (block.page, block.block_index))
    paragraphs: list[list[Block]] = []
    current: list[Block] = []
    for index, block in enumerate(ordered):
        current.append(block)
        next_block = ordered[index + 1] if index + 1 < len(ordered) else None
        if _ends_paragraph(block, next_block):
            paragraphs.append(current)
            current = []
    if current:
        paragraphs.append(current)
    return paragraphs


def _paragraph_text(paragraph: list[Block]) -> str:
    text = " ".join(block.text for block in paragraph)
    # Repair line-end hyphenation only when both sides are alphabetic.
    return normalize_space(HYPHEN_REPAIR_RE.sub("", text))


def _paragraph_segments(
    paragraph: list[Block],
) -> tuple[str, list[ChunkSegment]]:
    """Join the paragraph and map each repaired char back to its source block.

    The hyphen repair removes a few chars from the joined string, so the
    mapping is built char-by-char: every kept char records (text_position,
    block_index, block_local_position). Spaces between blocks belong to no
    block but still occupy text positions.
    """
    joined_parts: list[str] = []
    block_of: list[int] = []
    for block_index, block in enumerate(paragraph):
        if block_index:
            joined_parts.append(" ")
            block_of.append(-1)
        joined_parts.append(block.text)
        block_of.extend([block_index] * len(block.text))
    joined = "".join(joined_parts)

    removed: set[int] = set()
    for match in HYPHEN_REPAIR_RE.finditer(joined):
        removed.update(range(match.start(), match.end()))

    repaired: list[str] = []
    kept: list[tuple[int, int, int]] = []  # (text_position, block_index, block_local)
    block_local = [0] * len(paragraph)
    for position, char in enumerate(joined):
        if position in removed:
            continue
        block_index = block_of[position]
        if block_index >= 0:
            kept.append((len(repaired), block_index, block_local[block_index]))
            block_local[block_index] += 1
        repaired.append(char)
    text = "".join(repaired)

    segments: list[ChunkSegment] = []
    for block_index, block in enumerate(paragraph):
        positions = [(pos, local) for pos, bi, local in kept if bi == block_index]
        if not positions:
            continue
        segments.append(
            ChunkSegment(
                chunk_char_start=positions[0][0],
                chunk_char_end=positions[-1][0] + 1,
                block_id=block.block_id,
                block_char_start=positions[0][1],
                block_char_end=positions[-1][1] + 1,
                page=block.page,
                bboxes=[tuple(block.bbox)],
            )
        )
    return text, segments


def chunk_blocks(
    paper_id: str,
    blocks: list[Block],
    *,
    target_tokens: int = 420,
    max_tokens: int = 650,
) -> tuple[list[Chunk], list[Block]]:
    """Create retrievable chunks and assign paragraph indexes to source blocks."""

    paragraphs = paragraphize(blocks)
    updated_blocks: dict[str, Block] = {}
    paragraph_records: list[tuple[list[Block], str, int, list[ChunkSegment]]] = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        updated = [
            block.model_copy(update={"paragraph_index": paragraph_index}) for block in paragraph
        ]
        updated_blocks.update({block.block_id: block for block in updated})
        text, segments = _paragraph_segments(updated)
        paragraph_records.append((updated, text, estimate_tokens(text), segments))

    chunks: list[Chunk] = []
    buffer: list[tuple[list[Block], str, int, list[ChunkSegment]]] = []
    buffer_tokens = 0

    def flush() -> None:
        nonlocal buffer, buffer_tokens
        if not buffer:
            return
        flat = [block for paragraph, _, _, _ in buffer for block in paragraph]
        text = "\n\n".join(item[1] for item in buffer)
        # re-anchor per-paragraph segments into the chunk text (paragraphs
        # are joined with a two-newline separator)
        chunk_segments: list[ChunkSegment] = []
        offset = 0
        for _paragraph, paragraph_text, _, paragraph_segments in buffer:
            for segment in paragraph_segments:
                chunk_segments.append(
                    segment.model_copy(
                        update={
                            "chunk_char_start": offset + segment.chunk_char_start,
                            "chunk_char_end": offset + segment.chunk_char_end,
                        }
                    )
                )
            offset += len(paragraph_text) + 2
        index = len(chunks)
        content_hash = sha256_text(text)
        chunks.append(
            Chunk(
                chunk_id=f"ch-{paper_id}-{index:04d}-{content_hash[:8]}",
                # V4.1：DocumentGraph 统一——paper_version_id 从 block 继承
                # （解析阶段可为空串，to_chunks 以 version 补全）
                paper_id=paper_id,
                paper_version_id=flat[0].paper_version_id,
                section_id=flat[0].section_id,
                section_path=flat[0].section_path,
                page_start=min(block.page for block in flat),
                page_end=max(block.page for block in flat),
                block_ids=[block.block_id for block in flat],
                text=text,
                token_estimate=estimate_tokens(text),
                content_sha256=content_hash,
                segments=chunk_segments,
            )
        )
        buffer = []
        buffer_tokens = 0

    for record in paragraph_records:
        paragraph, _, tokens, _ = record
        boundary = bool(buffer and paragraph[0].section_id != buffer[-1][0][0].section_id)
        if boundary or (buffer and buffer_tokens + tokens > max_tokens):
            flush()
        buffer.append(record)
        buffer_tokens += tokens
        if buffer_tokens >= target_tokens:
            flush()
    flush()
    ordered_updated = [
        updated_blocks[block.block_id]
        for block in sorted(blocks, key=lambda b: (b.page, b.block_index))
    ]
    return chunks, ordered_updated
