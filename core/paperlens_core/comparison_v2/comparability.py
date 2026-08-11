"""ComparabilityKey + ResultRecord (改进方案2 Phase F §34-35).

A ResultRecord is the normalized, comparable unit: dataset + task + metric →
value.  Two papers are comparable on a metric when their keys align
(dataset normalized, metric normalized, task normalized).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from ..papers.models import PaperProfile


class ComparabilityKey(BaseModel):
    """Normalized key identifying one comparable measurement."""

    model_config = ConfigDict(extra="allow")

    dataset: str = ""
    task: str = ""
    metric: str = ""
    split: str = ""
    shot: str = ""
    backbone: str = ""
    pretraining: str = ""
    train_protocol: str = ""
    test_protocol: str = ""
    metric_direction: str = ""

    def normalized(self) -> "ComparabilityKey":
        return ComparabilityKey(
            dataset=_normalize_name(self.dataset),
            task=_normalize_name(self.task),
            metric=_normalize_name(self.metric),
            split=_normalize_name(self.split),
            shot=_normalize_name(self.shot),
            backbone=_normalize_name(self.backbone),
            pretraining=_normalize_name(self.pretraining),
            train_protocol=_normalize_name(self.train_protocol),
            test_protocol=_normalize_name(self.test_protocol),
            metric_direction=_normalize_name(self.metric_direction),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "dataset": self.dataset,
            "task": self.task,
            "metric": self.metric,
            "split": self.split,
            "shot": self.shot,
            "backbone": self.backbone,
            "pretraining": self.pretraining,
            "train_protocol": self.train_protocol,
            "test_protocol": self.test_protocol,
            "metric_direction": self.metric_direction,
        }


class ResultRecord(BaseModel):
    """One normalized result row (方案2 §35)."""

    model_config = ConfigDict(extra="allow")

    paper_version_id: str
    paper_id: str = ""

    key: ComparabilityKey = Field(default_factory=ComparabilityKey)
    value: float | None = None
    unit: str = ""
    raw_text: str = ""
    page: int = 0
    quote: str = ""
    evidence: list[dict[str, str]] = Field(default_factory=list)

    def comparable_with(self, other: "ResultRecord") -> bool:
        return self.key.normalized() == other.key.normalized()

    def as_dict(self) -> dict[str, object]:
        return {
            "paper_version_id": self.paper_version_id,
            "paper_id": self.paper_id,
            "key": self.key.as_dict(),
            "value": self.value,
            "unit": self.unit,
            "raw_text": self.raw_text,
            "quote": self.quote,
        }


def _normalize_name(name: str) -> str:
    """Normalize dataset/metric names: case + separators + common aliases."""
    name = (name or "").strip()
    name = name.lower()
    name = re.sub(r"[_\- ]+", " ", name)
    aliases = {
        "coco val2017": "coco",
        "coco test-dev": "coco",
        "ms coco": "coco",
        "imagenet val": "imagenet",
        "imagenet-1k": "imagenet",
        "map": "map",
        "mAP": "map",
    }
    return aliases.get(name, name)


def result_record_from_profile(
    profile: PaperProfile,
    *,
    paper_version_id: str | None = None,
) -> list[ResultRecord]:
    """Flatten all experiment records in a profile into ResultRecords."""
    version = paper_version_id or profile.paper_version_id
    records: list[ResultRecord] = []
    for experiment in profile.experiments:
        for result in experiment.results:
            key = ComparabilityKey(
                dataset=result.dataset,
                task="",
                metric=result.metric,
            )
            records.append(
                ResultRecord(
                    paper_version_id=version,
                    paper_id=profile.paper_id,
                    key=key,
                    value=result.value,
                    raw_text=result.paper_says,
                    quote=result.paper_says[:200],
                    evidence=experiment.source_evidence,
                )
            )
    return records
