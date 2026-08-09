"""Paragraph reconstruction from line-level blocks.

PDF line extraction yields one block per visual line (and per font-change
fragment inside a line). This module merges them back into full paragraphs:

1. same-band fragments (math subscripts, font changes) are joined into lines;
2. the page is split into columns when the x-distribution shows two stable
   clusters (two-column papers);
3. lines are merged into paragraphs per column using gap / sentence-end /
   indent rules, keeping headings, captions, formulas and media separate.

The output keeps the original Block model: paragraph blocks reuse the first
line's block_id/bbox so stable identity and evidence jumps still work.
"""

from __future__ import annotations

import re
from collections import Counter

from .models import Block, BlockType

_HEADING_LIKE = re.compile(
    r"^(?:\d+(?:\.\d+){0,3}[.)]?|[A-Z][.)]?|[IVXLCDM]+[.)]?)\s+\S", re.IGNORECASE
)
_CAPTION_LIKE = re.compile(r"^(?:Figure|Fig\.?|Table|Tab\.?)\s+\w+", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?。！？][\]\)\"'’”]*$")
_INDENT = 12.0


def _line_height(blocks: list[Block]) -> float:
    heights = [
        block.bbox[3] - block.bbox[1]
        for block in blocks
        if block.block_type == BlockType.TEXT
    ]
    if not heights:
        return 10.0
    return Counter(round(height, 1) for height in heights).most_common(1)[0][0]


def _body_font(blocks: list[Block]) -> float:
    sizes = [
        block.font_size
        for block in blocks
        if block.block_type == BlockType.TEXT and block.font_size
    ]
    if not sizes:
        return 10.0
    return Counter(round(size, 1) for size in sizes).most_common(1)[0][0]


def _join_fragments(parts: list[str]) -> str:
    text = ""
    for part in parts:
        if not text:
            text = part
        elif re.search(r"[A-Za-z]-$", text) and re.match(r"^[a-z]", part):
            text = text[:-1] + part
        else:
            text = text + " " + part
    return re.sub(r"\s+", " ", text).strip()


_TITLE_WORDS = {
    "abstract", "introduction", "background", "related work", "method", "methods",
    "methodology", "approach", "experiments", "experimental setup", "results",
    "discussion", "limitations", "conclusion", "conclusions", "references",
    "bibliography", "appendix", "appendices", "acknowledgements", "acknowledgment",
    "supplementary", "supplementary material", "keywords", "index terms",
}


def _is_table_row(text: str) -> bool:
    """Table data rows are runs of numeric cells ('✓ 10.0 19.2 9.2 13.5').
    Author lines ('Trevor Darrell 1') and reference entries ('pp. 9577-9586')
    have scattered numbers and must not match."""
    words = text.split()
    if len(words) < 3:
        return False
    streak = 0
    for word in words:
        if re.match(r"^[✓✗✔]?\d+(?:\.\d+)?%?$", word):
            streak += 1
            if streak >= 3:
                return True
        else:
            streak = 0
    return False


def _is_standalone_line(text: str, block: Block, body_font: float, median_width: float) -> bool:
    """Headings, captions, page numbers and short bold labels stay separate.

    Bold alone is not a heading: body text frequently contains bold phrases at
    full line width. A bold line only counts as a heading when it is visibly
    narrower than body lines (real headings are shorter than the column)."""
    if not text:
        return True
    if _CAPTION_LIKE.match(text):
        return True
    if _is_table_row(text):
        return True  # table data row stays separate
    if len(text) <= 4 and text.isdigit():
        return True  # page number
    words = text.split()
    normalized = text.casefold().rstrip(".:;")
    line_width = block.bbox[2] - block.bbox[0]
    larger = bool(block.font_size and block.font_size >= max(body_font * 1.08, 8.5))
    if len(words) <= 8 and _HEADING_LIKE.match(text):
        return True
    if len(words) <= 8 and larger:
        return True
    if len(words) <= 8 and block.is_bold:
        if line_width < median_width * 0.65:
            return True
        return False
    # short, narrow, title-like lines (e.g. unnumbered "Abstract" heading)
    if (
        len(words) <= 8
        and text[0].isupper()
        and not _SENTENCE_END.search(text)
        and normalized in _TITLE_WORDS
    ):
        return True
    return False


class _Line:
    __slots__ = ("x0", "y0", "x1", "y1", "text", "anchor")

    def __init__(self, x0: float, y0: float, x1: float, y1: float, text: str, anchor: Block):
        self.x0, self.y0, self.x1, self.y1, self.text, self.anchor = x0, y0, x1, y1, text, anchor


def _merge_lines(lines: list[_Line]) -> list[dict[str, object]]:
    """Merge lines into paragraphs using gap / sentence-end / indent rules."""
    if not lines:
        return []
    paragraphs: list[dict[str, object]] = []
    current: list[_Line] = []
    heights = [line.y1 - line.y0 for line in lines]
    line_h = max(Counter(round(h, 1) for h in heights).most_common(1)[0][0], 8.0)

    def flush() -> None:
        if not current:
            return
        text = _join_fragments([line.text for line in current])
        first = current[0]
        last = current[-1]
        paragraphs.append(
            {
                "bbox": (first.x0, first.y0, last.x1, last.y1),
                "text": text,
                "anchor": first.anchor,
            }
        )
        current.clear()

    for index, line in enumerate(lines):
        current.append(line)
        if index + 1 >= len(lines):
            continue
        next_line = lines[index + 1]
        gap = next_line.y0 - line.y1
        sentence_end = bool(_SENTENCE_END.search(line.text))
        if gap > line_h * 1.1:
            flush()
        elif sentence_end and gap > line_h * 0.45:
            flush()
        elif sentence_end and (next_line.x0 - line.x0) > _INDENT * 0.6:
            flush()
    flush()
    return paragraphs


def rebuild_paragraphs(
    blocks: list[Block], *, page_width: float | None = None, template=None
) -> list[Block]:
    """Rebuild paragraph-level blocks from line-level input blocks.

    ``template`` (TemplateFingerprint) pins the column boundary, line height
    and body font so parsing uses known layout values instead of heuristics.
    """
    pages: dict[int, list[Block]] = {}
    for block in blocks:
        # table cells (masked by the extractor) never join body paragraphs
        if block.metadata.get("table_cell"):
            continue
        pages.setdefault(block.page, []).append(block)

    rebuilt: list[Block] = []
    for page in sorted(pages):
        width = page_width
        if width is None:
            metadata = next(
                (block.metadata.get("page_width") for block in pages[page] if block.metadata.get("page_width")),
                None,
            )
            width = float(metadata) if metadata else 612.0
        rebuilt.extend(
            _rebuild_page(pages[page], page_width=width, page_number=page, template=template)
        )
    for index, block in enumerate(rebuilt):
        rebuilt[index] = block.model_copy(update={"block_index": index})
    return rebuilt


def _rebuild_page(
    blocks: list[Block], *, page_width: float, page_number: int = 0, template=None
) -> list[Block]:
    text_blocks = [block for block in blocks if block.block_type == BlockType.TEXT]
    special = [block for block in blocks if block.block_type != BlockType.TEXT]
    if not text_blocks:
        return special

    line_h = template.line_height if template else _line_height(text_blocks)
    body_font = template.body_font_size if template else _body_font(text_blocks)
    widths = sorted(
        block.bbox[2] - block.bbox[0]
        for block in text_blocks
        if block.bbox[2] - block.bbox[0] >= 50.0
    )
    median_width = widths[len(widths) // 2] if widths else page_width * 0.8

    # 1. coarse y-band grouping: fragments of the same visual line share a
    # baseline (y0 within 0.6 line heights). Bands may contain left+right
    # column rows at the same baseline, so rows are split by column below.
    text_blocks.sort(key=lambda block: (block.bbox[1], block.bbox[0]))
    groups: list[list[Block]] = []
    for block in text_blocks:
        # standalone fragments (headings, captions) never merge with the next
        # visual line, even when their baselines are close
        standalone = _is_standalone_line(block.text or "", block, body_font, median_width)
        if (
            groups
            and not standalone
            and abs(block.bbox[1] - groups[-1][0].bbox[1]) <= line_h * 0.6
        ):
            groups[-1].append(block)
        else:
            groups.append([block])

    # 2. column detection from the x0 of every text fragment (line-width
    # fragments only: page numbers and math subscripts are excluded).
    fragments_wide = [
        (fragment.bbox[0], fragment.bbox[2])
        for group in groups
        for fragment in group
        if fragment.bbox[2] - fragment.bbox[0] <= page_width * 0.55
        and fragment.bbox[2] - fragment.bbox[0] >= 50.0
    ]
    column_threshold: float | None = None
    if template is not None and template.column_count == 2 and template.left_col_x1 and template.right_col_x0:
        column_threshold = (template.left_col_x1 + template.right_col_x0) / 2
    elif len(fragments_wide) >= 4:
        starts = sorted(x0 for x0, _ in fragments_wide)
        gaps = [(starts[index + 1] - starts[index], index) for index in range(len(starts) - 1)]
        best_gap, split_index = max(gaps, key=lambda item: item[0])
        if best_gap > max(page_width * 0.05, 30.0):
            column_threshold = (starts[split_index] + starts[split_index + 1]) / 2

    # 3. split each band into visual lines: first by column side, then by
    # baseline. Fragments on the same baseline (y0 within a quarter line
    # height) are one visual line - math fragments like 'C' '∪ C' '∩ C'
    # share a baseline and must merge, regardless of the x gap between them.
    def make_line(fragments: list[Block]) -> _Line:
        x0 = min(fragment.bbox[0] for fragment in fragments)
        y0 = min(fragment.bbox[1] for fragment in fragments)
        x1 = max(fragment.bbox[2] for fragment in fragments)
        y1 = max(fragment.bbox[3] for fragment in fragments)
        return _Line(x0, y0, x1, y1, _join_fragments([f.text for f in fragments]), fragments[0])

    def _y_overlaps(first: Block, second: Block) -> bool:
        # main line and its super/subscripts share a horizontal band: their
        # bboxes overlap in y. Distinct lines do not overlap in y.
        return first.bbox[1] < second.bbox[3] and second.bbox[1] < first.bbox[3]

    lines: list[_Line] = []
    for group in groups:
        group.sort(key=lambda block: block.bbox[0])
        rows: dict[bool, list[Block]] = {}
        for fragment in group:
            if column_threshold is None:
                side = False
            else:
                side = fragment.bbox[0] >= column_threshold
            rows.setdefault(side, []).append(fragment)
        for side in sorted(rows):
            fragments = rows[side]
            fragments.sort(key=lambda block: (block.bbox[1], block.bbox[0]))
            visual_line: list[Block] = []
            for fragment in fragments:
                if visual_line and not _y_overlaps(visual_line[0], fragment):
                    lines.append(make_line(visual_line))
                    visual_line = []
                visual_line.append(fragment)
            if visual_line:
                lines.append(make_line(visual_line))

    # 4. per-column streams in reading order.
    narrow = [
        line
        for line in lines
        if line.x1 - line.x0 <= page_width * 0.55 and line.x1 - line.x0 >= 50.0
    ]
    columns: list[tuple[float, float]] = [(0.0, page_width)]
    if column_threshold is not None:
        left = [line for line in narrow if line.x0 < column_threshold]
        right = [line for line in narrow if line.x0 >= column_threshold]
        if left and right:
            left_x1 = Counter(round(line.x1, 1) for line in left).most_common(1)[0][0]
            right_x0 = Counter(round(line.x0, 1) for line in right).most_common(1)[0][0]
            if right_x0 - left_x1 > max(page_width * 0.02, 10.0):
                columns = [(0.0, left_x1 + 1.0), (right_x0 - 1.0, page_width)]

    # 3. per-column stream in reading order; standalone lines break paragraphs.
    # Full-width lines (spanning both columns) belong to the first stream only.
    output: list[Block] = []
    for column_index, (_col_x0, _col_x1) in enumerate(columns):
        if column_index == 0:
            candidates = (
                line for line in lines
                if column_threshold is None or line.x0 < column_threshold
            )
        else:
            candidates = (
                line for line in lines
                if column_threshold is not None and line.x0 >= column_threshold
            )
        stream = sorted(candidates, key=lambda line: (line.y0, line.x0))
        stream_meta = {"_stream": column_index}
        paragraph_lines: list[_Line] = []
        for line in stream:
            if _is_standalone_line(line.text, line.anchor, body_font, median_width):
                for para in _merge_lines(paragraph_lines):
                    output.append(_tag_stream(_make_block(para), stream_meta))
                paragraph_lines = []
                for para in _merge_lines([line]):
                    output.append(_tag_stream(_make_block(para), stream_meta))
            else:
                paragraph_lines.append(line)
        for para in _merge_lines(paragraph_lines):
            output.append(_tag_stream(_make_block(para), stream_meta))

    # column streams were emitted in reading order (left then right); keep
    # that order and only sort within each stream by y, then append special
    # blocks (formulas/media)
    result = sorted(
        output, key=lambda block: (block.metadata.get("_stream", 0), block.bbox[1])
    )
    result.extend(special)
    return result


def _tag_stream(block: Block, meta: dict[str, object]) -> Block:
    return block.model_copy(update={"metadata": {**block.metadata, **meta}})


def _make_block(paragraph: dict[str, object]) -> Block:
    anchor: Block = paragraph["anchor"]
    return anchor.model_copy(
        update={
            "text": paragraph["text"],
            "bbox": paragraph["bbox"],
        }
    )
