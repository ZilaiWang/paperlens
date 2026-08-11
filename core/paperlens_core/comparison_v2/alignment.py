"""Result alignment: build a matrix of comparable result rows (方案2 §36).

Given per-paper ResultRecords, align rows sharing the same ComparabilityKey,
then assemble an AlignedTable for the comparison UI.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .comparability import ComparabilityKey, ResultRecord


class AlignedTable(BaseModel):
    """Matrix view: rows = comparability keys, columns = papers."""

    model_config = ConfigDict(extra="allow")

    rows: list["AlignedRow"] = Field(default_factory=list)

    def as_matrix(self) -> dict[str, object]:
        return {
            "columns": list(self.columns()),
            "rows": [
                {
                    "key": row.key.as_dict(),
                    "cells": {
                        record.paper_version_id: {
                            "value": record.value,
                            "raw_text": record.raw_text,
                            "quote": record.quote,
                        }
                        for record in row.records
                    },
                }
                for row in self.rows
            ],
        }

    def columns(self) -> list[str]:
        seen: list[str] = []
        for row in self.rows:
            for record in row.records:
                if record.paper_version_id not in seen:
                    seen.append(record.paper_version_id)
        return seen


class AlignedRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: ComparabilityKey
    records: list[ResultRecord] = Field(default_factory=list)


def align_results(records: list[ResultRecord]) -> AlignedTable:
    """Group records by normalized comparability key."""
    groups: dict[str, list[ResultRecord]] = {}
    for record in records:
        key = record.key.normalized()
        groups.setdefault(_key_str(key), []).append(record)
    rows = [
        AlignedRow(key=group[0].key, records=group)
        for group in sorted(
            groups.values(),
            key=lambda g: (-len(g), g[0].key.metric),
        )
    ]
    return AlignedTable(rows=rows)


def align_results_row(
    records: list[ResultRecord],
    *,
    dataset: str = "",
    metric: str = "",
) -> list[ResultRecord]:
    """Return only the records matching a dataset/metric filter (raw filter)."""
    filtered = records
    if dataset:
        filtered = [
            r for r in filtered if dataset.lower() in r.key.dataset.lower()
        ]
    if metric:
        filtered = [
            r for r in filtered if metric.lower() in r.key.metric.lower()
        ]
    return filtered


def _key_str(key: ComparabilityKey) -> str:
    normalized = key.normalized()
    return f"{normalized.dataset}|{normalized.task}|{normalized.metric}"
