"""Evidence-bound empirical-ML quality assessment with deterministic totals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .evidence import build_evidence_ledger
from .llm import StructuredModel
from .models import QualityAssessment, QualityDimension
from .prompts import QUALITY_SYSTEM, evidence_package
from .retrieval import BM25Index


class StrEnum(str, Enum):
    """Python 3.10 compatible StrEnum (3.11+ has it built in)."""

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class RubricDimension:
    key: str
    label: str
    weight: int
    required_fields: tuple[str, ...]
    # English retrieval terms: the paper text is typically English, while the
    # rubric label is Chinese. Searching with the Chinese label alone would
    # return zero hits for English papers and starve the evidence package.
    search_query: str = ""


RUBRIC_VERSION = "empirical-ml-v1.1"
RUBRIC: tuple[RubricDimension, ...] = (
    RubricDimension(
        "problem", "研究问题与贡献清晰度", 10, ("问题", "缺口", "贡献", "相互一致"),
        search_query="research question contribution gap motivation problem",
    ),
    RubricDimension(
        "method", "方法论合理性", 20, ("假设", "关键步骤", "问题-方法对应"),
        search_query="method approach algorithm architecture assumption steps design",
    ),
    RubricDimension(
        "data", "数据与样本支撑", 15, ("来源", "规模", "划分", "泄漏控制"),
        search_query="dataset samples size split train validation test data",
    ),
    RubricDimension(
        "experiments", "实验、基线与消融", 20, ("基线", "公平设置", "消融或敏感性"),
        search_query="experiments baseline ablation sensitivity evaluation setting",
    ),
    RubricDimension(
        "metrics", "指标与统计证据", 15, ("指标适配", "方差或重复", "报告完整"),
        search_query="metric accuracy variance significance evaluation report",
    ),
    RubricDimension(
        "reproducibility", "可复现性", 10, ("代码数据", "超参数", "随机种子", "算力"),
        search_query="code data hyperparameter random seed implementation compute",
    ),
    RubricDimension(
        "limitations", "局限与外部有效性", 10, ("作者局限", "适用范围", "外推风险"),
        search_query="limitations future work external validity generalization scope",
    ),
)

SCORE_ANCHORS = {
    0: "完整检索后必需信息缺失，或证据明确显示严重设计缺陷",
    1: "只有主张，关键字段大多缺失",
    2: "基本方案可识别但至少一个重要字段缺失或薄弱",
    3: "核心字段有证据、设计基本合理，仍有次要缺口",
    4: "所有必需字段均有直接证据，并含稳健性或透明度要素",
}


class PaperProfile(StrEnum):
    """Strict enum so the model cannot produce an unsupported free-form profile."""

    EMPIRICAL_ML = "EMPIRICAL_ML"
    SURVEY = "SURVEY"
    THEORY = "THEORY"
    SYSTEM = "SYSTEM"
    POSITION = "POSITION"
    OTHER = "OTHER"


class QualityDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_profile: PaperProfile
    dimensions: list[QualityDimension] = Field(min_length=7, max_length=7)
    summary: str = Field(max_length=2000)
    caveats: list[str] = Field(default_factory=list, max_length=10)


def validate_and_score_quality(
    dimensions: list[QualityDimension],
    *,
    known_evidence_ids: set[str],
    assessable_keys: set[str] | None = None,
) -> QualityAssessment:
    """Validate dimension evidence and calculate the published weighted formula."""

    assessable_keys = assessable_keys or {dimension.key for dimension in RUBRIC}
    expected = {dimension.key: dimension for dimension in RUBRIC}
    provided = {dimension.name: dimension for dimension in dimensions}
    if len(provided) != len(dimensions):
        raise ValueError("quality dimensions contain duplicate names")
    unknown = set(provided) - set(expected)
    if unknown:
        raise ValueError(f"unknown rubric dimensions: {sorted(unknown)}")

    validated: list[QualityDimension] = []
    covered_weight = 0
    weighted_points = 0.0
    for key, rubric in expected.items():
        if key not in assessable_keys or key not in provided:
            continue
        result = provided[key]
        invalid = set(result.evidence_ids) - known_evidence_ids
        if invalid:
            raise ValueError(f"dimension {key} uses unknown evidence ids: {sorted(invalid)}")
        if result.score > 0 and not result.evidence_ids:
            raise ValueError(f"dimension {key} has a positive score without evidence")
        validated.append(result)
        covered_weight += rubric.weight
        weighted_points += rubric.weight * result.score / 4

    coverage = covered_weight / sum(dimension.weight for dimension in RUBRIC)
    total = round(weighted_points, 2) if coverage >= 0.70 else None
    caveats = [] if total is not None else ["可评估权重低于 70%，不发布总分。"]
    return QualityAssessment(
        dimensions=validated,
        weighted_score=total,
        evidence_coverage=round(coverage, 4),
        summary=f"Rubric {RUBRIC_VERSION}；总分由程序按公开权重计算。",
        caveats=caveats,
    )


def rubric_prompt_payload() -> list[dict[str, object]]:
    return [
        {
            "key": item.key,
            "label": item.label,
            "weight": item.weight,
            "required_fields": list(item.required_fields),
            "score_anchors": SCORE_ANCHORS,
        }
        for item in RUBRIC
    ]


class QualityAgent:
    """Independent, tool-bounded assessor; code retains authority over totals."""

    def __init__(self, model: StructuredModel):
        self.model = model

    def assess(self, *, chunks: list[object], paper_id: str, thread_id: str) -> QualityAssessment:
        index = BM25Index(chunks)  # type: ignore[arg-type]
        hits_by_id = {}
        for dimension in RUBRIC:
            query = dimension.search_query or " ".join(
                (dimension.label, *dimension.required_fields)
            )
            for hit in index.search(query, top_k=4):
                hits_by_id[hit.chunk.chunk_id] = hit
        hits = sorted(hits_by_id.values(), key=lambda hit: (hit.chunk.page_start, hit.rank))
        ledger = build_evidence_ledger(f"quality-{paper_id}", hits)
        payload = evidence_package(
            [
                {
                    "evidence_id": item.evidence_id,
                    "page": item.page_start,
                    "section": item.section_path,
                    "text": item.verbatim_excerpt,
                }
                for item in ledger
            ]
        )
        user = "\n\n".join(
            [
                "PAPER_PROFILE_REQUIRED: empirical machine-learning paper",
                "RUBRIC:\n" + json.dumps(rubric_prompt_payload(), ensure_ascii=False),
                payload,
                "OUTPUT_SCHEMA:\n"
                + json.dumps(QualityDraft.model_json_schema(), ensure_ascii=False),
            ]
        )
        draft = self.model.invoke_json(
            system=QUALITY_SYSTEM,
            user=user,
            schema=QualityDraft,
            stage="quality_agent",
            thread_id=thread_id,
        )
        if draft.paper_profile is not PaperProfile.EMPIRICAL_ML:
            return QualityAssessment(
                dimensions=[],
                weighted_score=None,
                evidence_coverage=0,
                summary=f"UNSUPPORTED_PROFILE（{draft.paper_profile.value}）："
                "当前 rubric 仅适用于实证型机器学习论文。",
                caveats=[draft.paper_profile.value, *draft.caveats],
            )
        assessment = validate_and_score_quality(
            draft.dimensions,
            known_evidence_ids={item.evidence_id for item in ledger},
        )
        return assessment.model_copy(
            update={
                "summary": draft.summary + f"（{assessment.summary}）",
                "caveats": [*draft.caveats, *assessment.caveats],
            }
        )
