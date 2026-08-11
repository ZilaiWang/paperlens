"""RegionFusion: region/object-level selection among backend candidates.

改进方案1 §三: 不再整页二选一——每个区域(正文/表格/公式/图注)选择最可信
来源。优先融合区域级候选；候选不足时退化为页级整体比较。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..ir.canonical import CanonicalNode
from .candidates import CandidateKind, ParseCandidate


@dataclass
class FusionOutcome:
    nodes: list[CanonicalNode] = field(default_factory=list)
    # region -> chosen backend (for audit)
    chosen_backends: dict[str, str] = field(default_factory=dict)
    # page -> chosen backend
    chosen_pages: dict[int, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _score_candidate(candidate: ParseCandidate, *, require_text: bool = True) -> float:
    score = candidate.confidence
    text = (candidate.text or "").strip()
    if require_text and not text:
        return -1.0
    if len(text) < 8 and candidate.kind not in (CandidateKind.FIGURE, CandidateKind.FORMULA):
        score -= 0.2  # tiny fragments are suspicious for body text
    return score


def group_candidates_by_region(candidates: list[ParseCandidate]) -> dict[str, list[ParseCandidate]]:
    """Group by page first (fallback), then by coarse region class."""
    groups: dict[str, list[ParseCandidate]] = {}
    for candidate in candidates:
        region = _region_key(candidate)
        groups.setdefault(region, []).append(candidate)
    return groups


def _region_key(candidate: ParseCandidate) -> str:
    kind = candidate.kind
    if kind == CandidateKind.TABLE or kind == CandidateKind.TABLE_CELL:
        return f"table-p{candidate.page}"
    if kind == CandidateKind.FORMULA:
        return f"formula-p{candidate.page}"
    if kind == CandidateKind.FIGURE:
        return f"figure-p{candidate.page}"
    if kind == CandidateKind.REFERENCE:
        return "references"
    return f"text-p{candidate.page}"


def _same_region(left: ParseCandidate, right: ParseCandidate) -> bool:
    if left.page != right.page or _region_key(left).split("-p", 1)[0] != _region_key(right).split("-p", 1)[0]:
        return False
    if left.bbox and right.bbox:
        lx0, ly0, lx1, ly1 = left.bbox
        rx0, ry0, rx1, ry1 = right.bbox
        intersection = max(0.0, min(lx1, rx1) - max(lx0, rx0)) * max(
            0.0, min(ly1, ry1) - max(ly0, ry0)
        )
        union = max(1.0, (lx1 - lx0) * (ly1 - ly0) + (rx1 - rx0) * (ry1 - ry0) - intersection)
        if intersection / union >= 0.25:
            return True
    left_text = " ".join(left.text.lower().split())
    right_text = " ".join(right.text.lower().split())
    return bool(left_text and right_text) and SequenceMatcher(None, left_text, right_text).ratio() >= 0.82


class RegionFusion:
    """Pick the most credible candidate per region across backends."""

    def __init__(self, *, region_level: bool = True):
        self.region_level = region_level

    def fuse(
        self,
        candidates_by_backend: dict[str, list[ParseCandidate]],
        *,
        canonicalizer: object,
        source_version_id: str,
        parse_run_id: str = "",
    ) -> FusionOutcome:
        if self.region_level and len(candidates_by_backend) > 1:
            return self._fuse_regions(
                candidates_by_backend,
                canonicalizer=canonicalizer,
                source_version_id=source_version_id,
                parse_run_id=parse_run_id,
            )
        return self._fuse_best_total(
            candidates_by_backend,
            canonicalizer=canonicalizer,
            source_version_id=source_version_id,
            parse_run_id=parse_run_id,
        )

    def _fuse_best_total(
        self,
        candidates_by_backend: dict[str, list[ParseCandidate]],
        *,
        canonicalizer: object,
        source_version_id: str,
        parse_run_id: str,
    ) -> FusionOutcome:
        """One backend wins the whole document (used when only one is available)."""
        outcome = FusionOutcome()
        best_backend: str | None = None
        best_score = float("-inf")
        for backend, candidates in candidates_by_backend.items():
            score = sum(max(0.0, _score_candidate(c)) for c in candidates) / max(1, len(candidates))
            if score > best_score:
                best_score = score
                best_backend = backend
        if best_backend is None:
            return outcome
        chosen = candidates_by_backend[best_backend]
        for index, candidate in enumerate(chosen):
            outcome.nodes.append(
                canonicalizer.canonize(
                    candidate,
                    source_version_id=source_version_id,
                    order_index=index,
                    parse_run_id=parse_run_id,
                )
            )
        for page in {c.page for c in chosen}:
            outcome.chosen_pages[page] = best_backend
        outcome.chosen_backends["document"] = best_backend
        outcome.notes.append(f"整篇选择 {best_backend}（唯一/总分最高）")
        return outcome

    def _fuse_regions(
        self,
        candidates_by_backend: dict[str, list[ParseCandidate]],
        *,
        canonicalizer: object,
        source_version_id: str,
        parse_run_id: str,
    ) -> FusionOutcome:
        """Region-level fusion: per region, per backend score, pick winner."""
        outcome = FusionOutcome()

        # Cluster matching objects across backends. A page is not a region:
        # grouping all body candidates as ``text-p1`` silently discarded every
        # paragraph except one on multi-backend runs.
        clusters: list[list[ParseCandidate]] = []
        candidates = [candidate for values in candidates_by_backend.values() for candidate in values]
        candidates.sort(key=lambda item: (item.page, item.bbox or (0, 0, 0, 0), item.candidate_id))
        for candidate in candidates:
            cluster = next(
                (items for items in clusters if any(_same_region(candidate, item) for item in items)),
                None,
            )
            if cluster is None:
                clusters.append([candidate])
            else:
                cluster.append(candidate)

        for cluster_index, cluster in enumerate(clusters):
            best = max(cluster, key=_score_candidate)
            best_backend = best.backend
            page = best.page
            node = canonicalizer.canonize(
                best,
                source_version_id=source_version_id,
                order_index=len(outcome.nodes),
                parse_run_id=parse_run_id,
            )
            outcome.nodes.append(node)
            region = f"{_region_key(best)}-{cluster_index:04d}"
            outcome.chosen_backends[region] = best_backend
            outcome.chosen_pages[page] = best_backend

        if not outcome.notes and len(candidates_by_backend) > 1:
            outcome.notes.append("区域级融合完成")

        # stable reading order: sort nodes by (page, y0, x0) where possible
        outcome.nodes.sort(
            key=lambda n: (
                n.page,
                (n.bbox[1] if n.bbox else 0.0),
                (n.bbox[0] if n.bbox else 0.0),
            )
        )
        for index, node in enumerate(outcome.nodes):
            node.order_index = index
        return outcome
