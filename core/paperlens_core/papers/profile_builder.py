"""PaperProfileBuilder: build a PaperProfile from a parsed paper.

Two strategies:
- ``build_offline``: deterministic extraction from section text (title,
  abstract, sections) that always works without a model.
- ``build_with_model``: enhance with LLM extraction of problem/method/
  experiments when a model is available.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    ExperimentRecord,
    ExperimentResult,
    MethodBlock,
    PaperProfile,
    ProblemStatement,
)


def _first_sentence(text: str, limit: int = 200) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    end = 0
    for match in re.finditer(r"[.!?。！？]\s", text):
        end = match.end()
        break
    if not end:
        end = min(len(text), limit)
    return text[:end].strip()


class PaperProfileBuilder:
    """Build profiles from documents.Block lists or arbitrary section dicts."""

    def __init__(self, model: object | None = None):
        self.model = model

    # ------------------------------------------------------------------
    def build_offline(
        self,
        *,
        paper_id: str,
        paper_version_id: str,
        title: str,
        abstract: str = "",
        sections: dict[str, str] | None = None,
        blocks: list[Any] | None = None,
        abbreviations: list[dict[str, str]] | None = None,
        symbols: list[str] | None = None,
        built_at: str = "",
    ) -> PaperProfile:
        sections = sections or self._sections_from_blocks(blocks or [])
        problem = self._extract_problem(sections)
        method = self._extract_method(sections)
        experiments = self._extract_experiments(sections)

        domain: list[str] = []
        joined = " ".join(sections.values()) + " " + abstract
        for hint, tag in (
            (r"object\s+detection|目标检测", "目标检测"),
            (r"semantic\s+segmentation|语义分割", "语义分割"),
            (r"large\s+language|大语言模型", "大语言模型"),
            (r"reinforcement\s+learning|强化学习", "强化学习"),
            (r"knowledge\s+graph|知识图谱", "知识图谱"),
            (r"image\s+generation|图像生成", "图像生成"),
        ):
            if re.search(hint, joined, re.IGNORECASE):
                domain.append(tag)

        return PaperProfile(
            paper_version_id=paper_version_id,
            paper_id=paper_id,
            title=title,
            abstract=abstract,
            domain=domain,
            problem=problem,
            method=method,
            experiments=experiments,
            abbreviations=abbreviations or [],
            symbols=symbols or [],
            built_at=built_at,
            status="DRAFT",
        )

    def build_with_model(
        self,
        *,
        paper_id: str,
        paper_version_id: str,
        title: str,
        abstract: str,
        sections: dict[str, str],
        model: object | None = None,
        stage: str = "profile_extract",
        thread_id: str = "",
    ) -> PaperProfile:
        """LLM-enhanced extraction into the ProfileSection JSON schema."""

        schema = _ProfileEnvelope
        response = (model or self.model).invoke_json(
            system=(
                "Extract a structured paper profile from the provided paper "
                "sections. Return JSON matching the schema."
            ),
            user=(
                f"TITLE: {title}\nABSTRACT: {abstract[:800]}\n"
                f"SECTIONS:\n" + "\n---\n".join(
                    f"[{k}]\n{v[:800]}" for k, v in sections.items()
                )
            ),
            schema=schema,
            stage=stage,
            thread_id=thread_id,
        )
        offline = self.build_offline(
            paper_id=paper_id,
            paper_version_id=paper_version_id,
            title=title,
            abstract=abstract,
            sections=sections,
        )
        profile = offline.model_copy(deep=True)
        if response.problem and response.problem.get("problem"):
            profile.problem = ProblemStatement(**response.problem)
        if response.method:
            profile.method = [MethodBlock(**m) for m in response.method]
        if response.experiments:
            profile.experiments = [
                ExperimentRecord(**e) for e in response.experiments
            ]
        profile.status = "COMPLETE"
        profile.version = "1.0"
        return profile

    # ------------------------------------------------------------------
    def _sections_from_blocks(self, blocks: list[Any]) -> dict[str, str]:
        sections: dict[str, str] = {}
        current: str = "Abstract"
        for block in blocks:
            block_type = str(getattr(block, "block_type", "") or "TEXT")
            text = getattr(block, "text", "") or ""
            if block_type == "HEADING":
                current = text.strip() or current
                sections.setdefault(current, "")
            else:
                sections[current] = sections.get(current, "") + "\n" + text
        return {k: v.strip() for k, v in sections.items() if v}

    def _extract_problem(self, sections: dict[str, str]) -> ProblemStatement:
        intro = (
            sections.get("Introduction")
            or sections.get("1 Introduction")
            or sections.get("引言")
            or ""
        )
        abstract_first = _first_sentence(sections.get("Abstract", ""))
        problem = ""
        motivation = ""
        challenges: list[str] = []
        for sentence in re.split(r"(?<=[.!?。！？])\s+", intro[:1500]):
            lowered = sentence.lower()
            if any(k in lowered for k in ("challenge", "difficult", "issue", "however")):
                challenges.append(sentence.strip()[:160])
            if not problem and any(k in lowered for k in ("we propose", "we present", "we introduce", "this paper", "in this work")):
                problem = sentence.strip()[:220]
            if not motivation and any(k in lowered for k in ("motivate", "importance", "crucial", "essential", "demand")):
                motivation = sentence.strip()[:200]
        if not problem:
            problem = abstract_first or _first_sentence(intro)
        return ProblemStatement(
            problem=problem,
            motivation=motivation,
            challenges=challenges[:5],
            research_questions=[],
            prior_limitations=[],
        )

    def _extract_method(self, sections: dict[str, str]) -> list[MethodBlock]:
        blocks: list[MethodBlock] = []
        method_section = (
            sections.get("Method")
            or sections.get("Methodology")
            or sections.get("方法")
            or sections.get("Proposed Method")
            or ""
        )
        for heading, text in sections.items():
            lowered = heading.lower()
            if any(k in lowered for k in ("approach", "method", "framework", "architecture", "pipeline", "our")):
                summary = _first_sentence(text, 160)
                blocks.append(
                    MethodBlock(
                        name=heading.strip(),
                        role="",
                        summary=summary,
                        evidence=[{"section": heading, "snippet": text[:200]}],
                    )
                )
        return blocks[:6] if blocks else (
            [MethodBlock(name="Method", summary=_first_sentence(method_section, 160))]
            if method_section else []
        )

    def _extract_experiments(self, sections: dict[str, str]) -> list[ExperimentRecord]:
        records: list[ExperimentRecord] = []
        experiment_section = (
            sections.get("Experiments")
            or sections.get("Experimental Setup")
            or sections.get("Results")
            or sections.get("实验")
            or sections.get("实验与结果")
            or ""
        )
        if not experiment_section:
            return records
        # try to capture metric rows: "metric: value" on dataset-ish context
        metric_pattern = re.compile(r"([A-Za-z][\w\s/+-]{2,40}?):\s*([0-9]*\.?[0-9]+)")
        rows = []
        for line in experiment_section.splitlines():
            line = line.strip()
            match = metric_pattern.search(line)
            if match:
                rows.append((match.group(1).strip(), match.group(2), line[:160]))
        if rows:
            record = ExperimentRecord(
                experiment_id="exp-offline-1",
                setup=_first_sentence(experiment_section, 200),
                results=[
                    ExperimentResult(
                        metric=metric,
                        value=float(value) if _safe_float(value) is not None else None,
                        paper_says=raw,
                    )
                    for metric, value, raw in rows[:20]
                ],
            )
            records.append(record)
        return records


def _safe_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class _ProfileEnvelope(BaseModel):
    """Model schema envelope for LLM profile extraction."""

    model_config = ConfigDict(extra="allow")

    problem: dict[str, object] = Field(default_factory=dict)
    method: list[dict[str, object]] = Field(default_factory=list)
    experiments: list[dict[str, object]] = Field(default_factory=list)
