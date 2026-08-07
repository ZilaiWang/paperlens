"""Asset caption association and citation callout extraction.

Figure/Table captions are matched to media regions by caption pattern and
proximity; in-text [n] citations are extracted as CitationCallout objects bound
to reference sequence numbers. Raster crops are produced client-side from the
PDF.js canvas (改进方案1.md §6.2), so no server-side rasterizer is required.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from .documents import Asset, CitationCallout, Section, stable_block_id

CAPTION_RE = re.compile(
    r"^(Figure|Fig\.?|Table|Tab\.?)\s+(\w+)[.:]?\s*(.*)", re.IGNORECASE
)
CALL_OUT_RE = re.compile(r"\[(\d+(?:\s*[-,]\s*\d+)*)\]")


def expand_citation_numbers(group: str) -> list[int]:
    """Expand a citation group like "3" / "3,5,8" / "3-5" into plain numbers.

    "[3-5]" must resolve to 3, 4, 5 (改进方案2.md §11.3), not just its two
    endpoints; a descending or oversized range is dropped rather than guessed.
    """
    numbers: list[int] = []
    for span in group.split(","):
        span = span.strip()
        if not span:
            continue
        if "-" in span:
            try:
                start, end = (int(part.strip()) for part in span.split("-", 1))
            except ValueError:
                continue
            if start <= end and end - start < 50:
                numbers.extend(range(start, end + 1))
            continue
        try:
            numbers.append(int(span))
        except ValueError:
            continue
    return numbers


def associate_captions(assets: list[Asset], blocks: list) -> list[Asset]:
    """Attach the nearest caption block (same page, nearest bbox) to each asset."""
    caption_candidates: list[tuple[int, tuple[float, float, float, float], str, str]] = []
    for block in blocks:
        text = (getattr(block, "text", "") or "").strip()
        match = CAPTION_RE.match(text)
        if not match:
            continue
        kind = "FIGURE" if match.group(1).lower().startswith("fig") else "TABLE"
        caption_candidates.append(
            (block.page, tuple(block.bbox), kind, text)
        )
    for asset in assets:
        candidates = [
            c for c in caption_candidates
            if c[0] == asset.page and c[2] == asset.asset_kind.value
        ]
        if not candidates:
            continue
        center_x = (asset.bbox[0] + asset.bbox[2]) / 2
        center_y = (asset.bbox[1] + asset.bbox[3]) / 2
        best = min(
            candidates,
            key=lambda c: abs((c[1][0] + c[1][2]) / 2 - center_x)
            + abs((c[1][1] + c[1][3]) / 2 - center_y),
        )
        if not asset.caption_original or len(best[3]) > len(asset.caption_original):
            asset.caption_original = best[3]
    return assets


def _scan_callouts(
    paper_version_id: str,
    blocks: list,
    reference_count: int,
    make_id: Callable[[object, re.Match[str]], str],
) -> list[CitationCallout]:
    """Shared [n] scan; make_id builds a stable callout id from (block, match).

    Callout reference IDs follow the app-wide convention
    ``ref-{version_id[:10]}-{sequence}`` so the frontend can bind body
    citations to ReferenceEntry records (改进方案2.md §11.2).
    """
    callouts: list[CitationCallout] = []
    for block in blocks:
        text = (getattr(block, "text", "") or "")
        for match in CALL_OUT_RE.finditer(text):
            numbers = expand_citation_numbers(match.group(1))
            valid = [number for number in numbers if 1 <= number <= reference_count]
            if not valid:
                continue
            callouts.append(
                CitationCallout(
                    callout_id=make_id(block, match),
                    paper_version_id=paper_version_id,
                    block_id=block.block_id,
                    char_start=match.start(),
                    char_end=match.end(),
                    raw=match.group(0),
                    reference_id=f"ref-{paper_version_id[:10]}-{valid[0]}",
                )
            )
    return callouts


def extract_callouts(
    paper_version_id: str,
    blocks: list,
    sections: list[Section],
    reference_count: int,
) -> list[CitationCallout]:
    """Extract [n] citation spans in body text and bind them to references."""
    references_start = next(
        (section.start_page for section in sections if section.canonical_name == "references"),
        None,
    )
    body = [block for block in blocks if references_start is None or block.page < references_start]
    return _scan_callouts(
        paper_version_id,
        body,
        reference_count,
        make_id=lambda block, match: stable_block_id(
            paper_version_id, block.page, tuple(block.bbox), match.group(0)
        ),
    )


def extract_callouts_html(
    paper_version_id: str,
    blocks: list,
    reference_count: int,
) -> list[CitationCallout]:
    """HTML path (改进方案2.md §4): the ltx_biblist is excluded from blocks at
    parse time, so every block is a callout source. IDs derive from the block id
    plus char span because logical pages carry no physical bbox."""
    return _scan_callouts(
        paper_version_id,
        blocks,
        reference_count,
        make_id=lambda block, match: (
            f"co-{paper_version_id[:10]}-{block.block_id}-{match.start()}"
        ),
    )
