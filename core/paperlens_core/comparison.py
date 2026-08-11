"""Deterministic assembly of evidence-bound 2-3 paper comparisons."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .evidence import build_evidence_ledger
from .llm import StructuredModel
from .models import CoverageStatus
from .prompts import COMPARISON_EXTRACTOR_SYSTEM, evidence_package
from .retrieval import BM25Index

# V4.7b（审计 2.4）：默认 5 个核心字段——13 字段全量抽取耗时翻倍且
# 多数单元格价值低；其余字段由前端按需传入
DEFAULT_COMPARISON_FIELDS = (
    "task_definition",
    "method_core",
    "datasets_and_samples",
    "metrics",
    "main_results",
)


class ComparisonCell(BaseModel):
    paper_id: str
    field: str
    value: str = ""
    status: CoverageStatus
    evidence_ids: list[str] = Field(default_factory=list, max_length=6)
    note: str = ""
    # V4.7（审计 P1）：证据引文与定位——前端可展开核实、可跳转原文
    quotes: list[str] = Field(default_factory=list, max_length=9)
    locators: list[dict[str, object]] = Field(default_factory=list, max_length=9)


class ResultComparison(BaseModel):
    """V4.7（审计 P1/2.2）：结构化结果记录对比（ComparabilityKey 对齐）。

    same_key=True 才允许比较数值；否则标记 Not directly comparable。
    """

    dataset: str
    metric: str
    conditions: dict[str, str] = Field(default_factory=dict)  # paper_id -> 条件摘要
    values: dict[str, str] = Field(default_factory=dict)  # paper_id -> 数值
    same_key: bool = True
    best_paper: str = ""  # same_key 时的最佳值来源
    records: list[dict[str, object]] = Field(default_factory=list)


class ComparisonTable(BaseModel):
    paper_ids: list[str]
    fields: list[str]
    cells: list[ComparisonCell]
    warnings: list[str] = Field(default_factory=list)


class PaperComparisonDraft(BaseModel):
    paper_id: str
    cells: list[ComparisonCell]


def assemble_comparison(
    paper_ids: list[str],
    extracted_cells: list[ComparisonCell],
    *,
    fields: list[str] | None = None,
    known_evidence: dict[str, set[str]] | None = None,
) -> ComparisonTable:
    if not 2 <= len(paper_ids) <= 3:
        raise ValueError("comparison requires 2 or 3 papers")
    if len(set(paper_ids)) != len(paper_ids):
        raise ValueError("paper IDs must be unique")
    fields = fields or list(DEFAULT_COMPARISON_FIELDS)
    known_evidence = known_evidence or {}
    index = {(cell.paper_id, cell.field): cell for cell in extracted_cells}
    cells: list[ComparisonCell] = []
    for field in fields:
        for paper_id in paper_ids:
            cell = index.get((paper_id, field))
            if cell is None:
                cell = ComparisonCell(
                    paper_id=paper_id,
                    field=field,
                    status=CoverageStatus.NOT_FOUND_IN_SEARCHED_SECTIONS,
                    note="尚未完成该字段抽取；不能推断为论文未报告。",
                )
            invalid = set(cell.evidence_ids) - known_evidence.get(paper_id, set(cell.evidence_ids))
            if invalid:
                raise ValueError(
                    f"comparison cell uses evidence from the wrong paper: {sorted(invalid)}"
                )
            if cell.status == CoverageStatus.FOUND and (not cell.value or not cell.evidence_ids):
                raise ValueError("FOUND comparison cells require a value and evidence")
            cells.append(cell)
    warnings = [
        "任务定义、数据集或指标不一致时不可直接按数值排名。",
        "‘未找到’与‘论文已确认未报告’是不同状态。",
    ]
    return ComparisonTable(paper_ids=paper_ids, fields=fields, cells=cells, warnings=warnings)


class PaperComparator:
    """Extract each paper independently, then let code assemble the table."""

    FIELD_QUERIES = {
        "task_definition": "task definition problem formulation",
        "research_question": "research question motivation contribution",
        "method_core": "method approach algorithm architecture",
        "training_setup": "training fine-tuning frozen optimizer epochs",
        "inference_setup": "inference test prediction setup",
        "datasets_and_samples": "dataset samples split train validation test",
        "baselines": "baseline comparison state of the art",
        "metrics": "evaluation metric AP accuracy mAP IoU",
        "main_results": "main results performance table",
        "ablations": "ablation sensitivity analysis",
        "author_limitations": "limitations failure cases future work",
        "code_and_data": "code data availability implementation reproducibility",
        "version_status": "publication version arxiv conference journal",
    }

    def __init__(self, model: StructuredModel):
        self.model = model

    def extract_one(
        self,
        *,
        paper_id: str,
        chunks: list[object],
        fields: list[str],
        thread_id: str,
    ) -> tuple[list[ComparisonCell], set[str]]:
        index = BM25Index(chunks)  # type: ignore[arg-type]
        selected = {}
        for field in fields:
            query = self.FIELD_QUERIES.get(field, field.replace("_", " "))
            for hit in index.search(query, top_k=3):
                selected[hit.chunk.chunk_id] = hit
        hits = list(selected.values())
        ledger = build_evidence_ledger(f"compare-{paper_id}", hits)
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
        user = "\n\n".join(
            [
                f"PAPER_ID: {paper_id}",
                "FIELDS: " + json.dumps(fields, ensure_ascii=False),
                package,
                "OUTPUT_SCHEMA:\n"
                + json.dumps(PaperComparisonDraft.model_json_schema(), ensure_ascii=False),
            ]
        )
        draft = self.model.invoke_json(
            system=COMPARISON_EXTRACTOR_SYSTEM,
            user=user,
            schema=PaperComparisonDraft,
            stage="comparison_extract",
            thread_id=thread_id,
        )
        if draft.paper_id != paper_id:
            raise ValueError("comparison extractor returned another paper_id")
        allowed_fields = set(fields)
        if {cell.field for cell in draft.cells} != allowed_fields:
            raise ValueError("comparison extractor must return exactly the requested fields")
        known = {item.evidence_id for item in ledger}
        ledger_by_id = {item.evidence_id: item for item in ledger}
        for cell in draft.cells:
            if cell.paper_id != paper_id:
                raise ValueError("comparison cell crosses paper boundary")
            if set(cell.evidence_ids) - known:
                raise ValueError("comparison cell uses unknown evidence")
            if cell.status == CoverageStatus.FOUND and not cell.evidence_ids:
                raise ValueError("FOUND comparison cell lacks evidence")
            # V4.7（审计 P1/2.3）：引文与定位随单元格返回，前端可核实可跳转
            #（截断到模型上限：模型可能为单格输出 12+ 条证据）
            cell.evidence_ids = cell.evidence_ids[:6]
            for eid in cell.evidence_ids:
                item = ledger_by_id.get(eid)
                if item is None:
                    continue
                if len(cell.quotes) >= 9:
                    break
                cell.quotes.append(item.verbatim_excerpt[:240])
                cell.locators.append(
                    {
                        "page": item.page_start,
                        "section": item.section_path,
                        "block_ids": item.block_ids,
                    }
                )
        return draft.cells, known

    def compare(
        self,
        papers: dict[str, list[object]],
        *,
        fields: list[str] | None,
        thread_id: str,
    ) -> ComparisonTable:
        paper_ids = list(papers)
        chosen_fields = fields or list(DEFAULT_COMPARISON_FIELDS)
        extracted: list[ComparisonCell] = []
        evidence: dict[str, set[str]] = {}
        for paper_id, chunks in papers.items():
            cells, known = self.extract_one(
                paper_id=paper_id,
                chunks=chunks,
                fields=chosen_fields,
                thread_id=thread_id,
            )
            extracted.extend(cells)
            evidence[paper_id] = known
        return assemble_comparison(
            paper_ids,
            extracted,
            fields=chosen_fields,
            known_evidence=evidence,
        )

# ---------------------------------------------------------------------------
# V4.5：TopicAlignmentGate + 可比性判定
# ---------------------------------------------------------------------------

TOPIC_ALIGNMENT_SYSTEM = """Judge whether the given papers address the SAME
research task. Use ONLY the provided summaries (never invent). Output one of:
SAME_TASK（完全同任务，可数值比较）/ RELATED（相近任务，仅方法思想对照）/
DIFFERENT（任务不同，不适合直接比较）。简短说明判断依据。"""


class TopicAlignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alignment: Literal["SAME_TASK", "RELATED", "DIFFERENT"]
    rationale: str = Field(max_length=500)
    # V4.7（审计 P4/3.6）：判定置信度与依据字段
    confidence: float = Field(default=0.5, ge=0, le=1)
    evidence_fields: list[str] = Field(default_factory=list)


def judge_topic_alignment(
    *,
    model: StructuredModel,
    papers: list[dict[str, str]],  # [{paper_id, task, method, metrics}]
    thread_id: str,
) -> TopicAlignment:
    """基于各论文的 task/method/metrics 摘要判断可比性（不重复抽取）。

    V4.7（审计 P0/2.1）：papers 摘要必须来自本次抽取的 cells——此前
    喂空 artifact 字段导致 DIFFERENT 且 rationale 声称'字段均为空'，
    与同响应中 FOUND 的 cells 自相矛盾。此处对空摘要显式拒绝，
    要求调用方先抽取。
    """
    if len(papers) < 2:
        raise ValueError("need at least 2 papers")
    if not any(p.get("task") or p.get("method") or p.get("metrics") for p in papers):
        raise ValueError("topic alignment needs extracted summaries (cells)")
    try:
        return model.invoke_json(
            system=TOPIC_ALIGNMENT_SYSTEM,
            user=json.dumps({"papers": papers}, ensure_ascii=False),
            schema=TopicAlignment,
            stage="topic_alignment",
            thread_id=thread_id,
            temperature=0.0,
        )
    except Exception:  # noqa: BLE001 - deterministic fallback
        return _fallback_alignment(papers)


def _fallback_alignment(papers: list[dict[str, str]]) -> TopicAlignment:
    """无 LLM 时的确定性兜底：关键词重叠率。"""
    import re

    def tokens(text: str) -> set[str]:
        return set(re.findall(r"[a-z]{3,}", (text or "").casefold()))

    base = tokens(papers[0].get("task", "")) | tokens(papers[0].get("method", ""))
    if not base:
        return TopicAlignment(
            alignment="RELATED", rationale="缺少任务摘要，保守判定为相近任务。",
            confidence=0.3, evidence_fields=[],
        )
    ratios = []
    for paper in papers[1:]:
        other = tokens(paper.get("task", "")) | tokens(paper.get("method", ""))
        union = base | other
        ratios.append(len(base & other) / len(union) if union else 0.0)
    average = sum(ratios) / len(ratios)
    if average >= 0.35:
        return TopicAlignment(
            alignment="SAME_TASK", rationale=f"任务/方法词重叠率 {average:.2f}。",
            confidence=round(average, 2), evidence_fields=["task", "method"],
        )
    if average >= 0.15:
        return TopicAlignment(
            alignment="RELATED", rationale=f"任务/方法词重叠率 {average:.2f}。",
            confidence=round(average, 2), evidence_fields=["task", "method"],
        )
    return TopicAlignment(
        alignment="DIFFERENT", rationale=f"任务/方法词重叠率 {average:.2f}。",
        confidence=round(1 - average, 2), evidence_fields=["task", "method"],
    )


def add_comparability_warnings(
    table: ComparisonTable,
    *,
    alignment: str = "SAME_TASK",
) -> ComparisonTable:
    """V4.5 §13.3：条件键不一致时禁止数值比较——按字段级警示。"""
    warnings = list(table.warnings)
    if alignment != "SAME_TASK":
        warnings.insert(
            0,
            "这些论文可以进行方法思想对照，但不宜直接比较实验数值。"
            if alignment == "RELATED"
            else "这些论文任务不同，不建议直接比较。",
        )
    table.warnings = warnings
    return table

# ---------------------------------------------------------------------------
# V4.7（审计 P1/2.2）：结构化结果对比（ComparabilityKey 对齐）
# ---------------------------------------------------------------------------

def build_result_comparisons(
    records_by_paper: dict[str, list[dict[str, object]]],
) -> list[ResultComparison]:
    """把各篇的 ResultRecord 按 (dataset, metric, condition) 对齐。

    same_key 需要 dataset + metric 一致且条件摘要兼容（空条件视为通配）；
    同 key 才允许标记最佳值，否则前端显示 Not directly comparable。
    """
    groups: dict[tuple[str, str], ResultComparison] = {}
    for paper_id, records in records_by_paper.items():
        for record in records:
            dataset = str(record.get("dataset") or "")
            metric = str(record.get("metric") or "")
            key = (dataset, metric)
            group = groups.setdefault(
                key,
                ResultComparison(dataset=dataset, metric=metric),
            )
            condition = str(record.get("condition") or "")
            group.conditions[paper_id] = condition
            group.values[paper_id] = str(record.get("value") or "")
            group.records.append(
                {
                    "paper_id": paper_id,
                    "method": str(record.get("method") or ""),
                    "value": str(record.get("value") or ""),
                    "condition": condition,
                    "row": record.get("row"),
                    "column": record.get("column"),
                }
            )
    results = list(groups.values())
    for group in results:
        # 条件不一致 → 不可直接比较（空条件 = 未报告条件，视为通配）
        conditions = {v for v in group.conditions.values() if v}
        group.same_key = len(conditions) <= 1
        if not group.same_key:
            continue
        numeric = {}
        for paper_id, value in group.values.items():
            try:
                numeric[paper_id] = float(value.replace("%", "").strip())
            except ValueError:
                continue
        if numeric:
            group.best_paper = max(numeric, key=numeric.get)
    return results


# ---------------------------------------------------------------------------
# V4.7（审计 P4/1.5）：跨论文比较问答（CrossPaperClaim）
# ---------------------------------------------------------------------------

CROSS_PAPER_QA_SYSTEM = """Answer a question ACROSS the given papers. Use ONLY
the provided per-paper cells and their evidence quotes. For every part of the
answer, attribute it to the exact paper(s): paper_A_evidence / paper_B_evidence
etc. Never mix a paper's evidence with another paper's claim. When conditions
or metrics are incompatible, set comparability_status accordingly and explain
the caveat. Output strictly one JSON object.

Write claim and caveat in Chinese (中文), concise. Keep metric/dataset/model
names in their conventional forms (mAP, COCO, ...)."""


# ---------------------------------------------------------------------------
# 2026-08-06：对比单元格中文翻译——比较完成后一次 LLM 批量翻译全部有值
# 单元格（5 字段 × N 篇 ≈ 10-15 条），存进 comparison payload 供前端表格
# 双语展示；失败降级为无翻译（不阻塞比较）
# ---------------------------------------------------------------------------

CELL_TRANSLATION_SYSTEM = """Translate the values of the given JSON object from
English into concise, natural Chinese (中文). Keep numbers, metric names
(mAP, AP50, FLOPs...), dataset names (COCO, PASCAL VOC...) and model names in
their conventional forms. Output strictly one JSON object:
{"translations": {"<same key>": "<Chinese text>", ...}} — every input key must
appear exactly once. No explanations."""


class CellTranslationsDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    translations: dict[str, str] = Field(default_factory=dict)


def translate_cell_values_zh(
    model: StructuredModel, items: dict[str, str]
) -> dict[str, str]:
    """Batch-translate comparison cell values into Chinese (best-effort)."""
    if not items:
        return {}
    try:
        draft = model.invoke_json(
            system=CELL_TRANSLATION_SYSTEM,
            user=json.dumps(items, ensure_ascii=False),
            schema=CellTranslationsDraft,
            stage="cell_translation",
            thread_id="cell-translation",
        )
        return {
            key: value
            for key, value in (draft.translations or {}).items()
            if value and key in items
        }
    except Exception:  # noqa: BLE001 - translation is a display nicety
        return {}


class CrossPaperAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1, max_length=800)
    paper_evidence: dict[str, list[str]] = Field(default_factory=dict)  # paper_id -> quotes
    comparability_status: Literal["COMPARABLE", "PARTIAL", "NOT_COMPARABLE"] = "PARTIAL"
    caveat: str = ""


def answer_cross_paper_question(
    *,
    model: StructuredModel,
    question: str,
    cells_by_paper: dict[str, list[ComparisonCell]],
    thread_id: str,
    history: list[dict[str, str]] | None = None,
    cell_translations: dict[str, str] | None = None,
) -> CrossPaperAnswer:
    """跨论文问答：只基于各篇已抽取的 cells + 证据引文作答。

    V4.7f：支持多轮对话历史（指代消解用，历史不作事实证据）。
    2026-08-06：默认中文——单元格值优先使用比较时生成的 cell_translations
    （key = f"{paper_id}|{field}"），回答（claim/caveat）由模型用中文输出。
    """
    payload = {
        "question": question,
        "history": (history or [])[-6:],
        "papers": {
            paper_id: [
                {
                    "field": cell.field,
                    "value": (
                        cell_translations.get(f"{paper_id}|{cell.field}")
                        if cell_translations
                        else ""
                    )
                    or cell.value,
                    "quotes": cell.quotes[:3],
                }
                for cell in cells
                if cell.status == CoverageStatus.FOUND
            ]
            for paper_id, cells in cells_by_paper.items()
        },
    }
    try:
        return model.invoke_json(
            system=CROSS_PAPER_QA_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            schema=CrossPaperAnswer,
            stage="cross_paper_qa",
            thread_id=thread_id,
            temperature=0.0,
        )
    except Exception:  # noqa: BLE001 - QA is best-effort
        return CrossPaperAnswer(
            claim="（跨论文问答暂不可用，请重试或查看对比矩阵。）",
            comparability_status="PARTIAL",
            caveat="LLM 调用失败降级",
        )
