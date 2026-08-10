"""Evidence-grounded profile for overview and analysis features.

Every field carries status + value + evidence_links; the profile is built once
per paper and reused by quality audit and multi-paper comparison instead of
each analysis re-reading the paper.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from .evidence import build_evidence_ledger
from .llm import StructuredModel
from .prompts import evidence_package
from .retrieval import BM25Index

PROFILE_VERSION = "cv-profile-v0.1"


class ProfileField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "NOT_FOUND_IN_SEARCHED_SECTIONS"  # FOUND / NOT_FOUND_IN_SEARCHED_SECTIONS / NOT_REPORTED_CONFIRMED / PARSE_GAP / NOT_APPLICABLE
    value: str = ""
    evidence_ids: list[str] = Field(default_factory=list, max_length=6)
    checked_sections: list[str] = Field(default_factory=list)
    missing_reason: str = ""
    # V4.3-2：证据定位（evidence → chunk/block 锚点），前端可跳到原文
    evidence_locators: list[dict[str, object]] = Field(default_factory=list)


class CVProfileDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: ProfileField
    method: ProfileField
    datasets: ProfileField
    protocols: ProfileField
    metrics: ProfileField
    main_results: ProfileField
    ablations: ProfileField
    reproducibility: ProfileField
    limitations: ProfileField


class UnderstandingArtifact(BaseModel):
    """V4.3-2：版本化论文理解产物。

    单篇概览/质量/问答/多篇比较共享的事实源——随版本持久化
    （documents kind="understanding_artifact"），带 schema/extractor 版本
    与字段级证据定位。
    """

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    paper_version_id: str
    schema_version: str = "understanding-v1"
    extractor_version: str = PROFILE_VERSION
    generated_at: str = ""
    profile: CVProfileDraft


# retrieval queries per field (English; paper text is English)
FIELD_QUERIES: dict[str, str] = {
    "task": "task definition problem formulation setting input output",
    "method": "method approach architecture backbone modules loss training inference",
    "datasets": "dataset samples split train validation test benchmark",
    "protocols": "evaluation protocol setup shots seed pretraining image size",
    "metrics": "evaluation metric AP accuracy mAP IoU",
    "main_results": "main results performance table state of the art",
    "ablations": "ablation sensitivity analysis component",
    "reproducibility": "code data hyperparameter learning rate optimizer hardware",
    "limitations": "limitations failure cases future work",
}

CV_PROFILE_SYSTEM = """You build an evidence-grounded CV paper profile. For every requested field:
- status FOUND when the evidence package supports a value; otherwise
  NOT_FOUND_IN_SEARCHED_SECTIONS (searched, not found), NOT_REPORTED_CONFIRMED
  (only when the input certifies exhaustive search), PARSE_GAP, or NOT_APPLICABLE.
- value must be short and factual; cite 1-3 evidence IDs from the package.
- checked_sections names the sections you actually searched.
Never invent numbers, dataset names, metrics or conditions. Keep method names
and metrics in English. Output strict JSON with exactly the nine fields.""".strip()


class CVProfileBuilder:
    def __init__(self, model: StructuredModel):
        self.model = model

    def build(
        self,
        *,
        chunks: list[object],
        paper_id: str,
        thread_id: str,
    ) -> CVProfileDraft:
        index = BM25Index(chunks)  # type: ignore[arg-type]
        hits_by_id: dict[str, object] = {}
        for _field, query in FIELD_QUERIES.items():
            for hit in index.search(query, top_k=4):
                hits_by_id[hit.chunk.chunk_id] = hit
        hits = sorted(hits_by_id.values(), key=lambda hit: (hit.chunk.page_start, hit.rank))
        ledger = build_evidence_ledger(f"profile-{paper_id}", hits)
        package = evidence_package(
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
        known_ids = {item.evidence_id for item in ledger}
        user = "\n\n".join(
            [
                f"PAPER_ID: {paper_id}",
                "FIELDS: " + json.dumps(list(FIELD_QUERIES), ensure_ascii=False),
                package,
                "OUTPUT_SCHEMA:\n"
                + json.dumps(CVProfileDraft.model_json_schema(), ensure_ascii=False),
            ]
        )
        draft = self.model.invoke_json(
            system=CV_PROFILE_SYSTEM,
            user=user,
            schema=CVProfileDraft,
            stage="cv_profile",
            thread_id=thread_id,
            temperature=0.0,
        )
        # deterministic gate: strip unknown evidence ids and downgrade status
        for field_name in FIELD_QUERIES:
            field_obj = getattr(draft, field_name)
            invalid = [eid for eid in field_obj.evidence_ids if eid not in known_ids]
            if invalid:
                field_obj.evidence_ids = [eid for eid in field_obj.evidence_ids if eid in known_ids]
            if field_obj.status == "FOUND" and not field_obj.evidence_ids:
                field_obj.status = "NOT_FOUND_IN_SEARCHED_SECTIONS"
                field_obj.missing_reason = "FOUND 状态缺少有效证据，已降级"
        # V4.3-2：字段证据定位（evidence_id → 锚点），前端跳原文用
        ledger_by_id = {item.evidence_id: item for item in ledger}
        for field_name in FIELD_QUERIES:
            field_obj = getattr(draft, field_name)
            field_obj.evidence_locators = [
                {
                    "evidence_id": item.evidence_id,
                    "page": item.page_start,
                    "section": item.section_path,
                    "block_ids": item.block_ids,
                }
                for item in (ledger_by_id[eid] for eid in field_obj.evidence_ids if eid in ledger_by_id)
            ]
        return draft
