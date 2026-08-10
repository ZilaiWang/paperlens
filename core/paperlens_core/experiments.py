"""Deterministically extract experiment records from structured table assets.

ResultRecord preserves dataset, metric, value, and table location without an
LLM. Figures, formulas, and borderless table images are not interpreted here.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from .documents import Asset, AssetKind

# 常见指标词（用于把数字行归类为结果行）
_METRIC_HINTS = (
    "ap", "map", "mAP", "iou", "acc", "accuracy", "f1", "recall", "precision",
    "bleu", "psnr", "ssim", "latency", "flops", "params", "dice", "top-1",
    "top-5", "err", "error", "nmi", "ari",
)


class ResultRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: str
    dataset: str = ""
    metric: str = ""
    condition: str = ""       # shot/backbone/pretraining 等条件摘要
    method: str = ""          # 行首方法名（Ours/baseline 名）
    value: str = ""
    row: int = 0
    column: int = 0


def _looks_like_value(cell: str) -> bool:
    return bool(re.fullmatch(r"[-−+]?\d+(?:\.\d+)?(?:%|±[\d.]+)?", cell.strip()))


def _first_text_cell(row: list[str]) -> str:
    for cell in row:
        if cell and cell.strip() and not _looks_like_value(cell):
            return cell.strip()
    return ""


def extract_result_records(assets: list[Asset]) -> list[ResultRecord]:
    """从 TABLE 资产的 structured_data.rows 提取结果记录。

    启发式：含数值单元格且同行/表头出现指标词的行视为结果行；
    行首文本单元格视为方法名，数字列第一个为值。
    """
    records: list[ResultRecord] = []
    for asset in assets:
        if asset.asset_kind != AssetKind.TABLE:
            continue
        rows = (asset.structured_data or {}).get("rows") or []
        if not rows:
            continue
        header = [str(cell).strip() for cell in rows[0]] if rows else []
        metric_column = -1
        for index, cell in enumerate(header):
            if any(hint in cell.casefold() for hint in _METRIC_HINTS):
                metric_column = index
                break
        for row_index, row in enumerate(rows[1:], start=1):
            cells = [str(cell).strip() for cell in row]
            # 指标列必须落在行内（行可能比表头短）
            value_index = (
                metric_column
                if 0 <= metric_column < len(cells)
                else next(
                    (i for i, cell in enumerate(cells) if _looks_like_value(cell)), -1
                )
            )
            if value_index < 0:
                continue
            method = _first_text_cell(cells)
            if not method:
                continue
            records.append(
                ResultRecord(
                    table_id=asset.asset_id,
                    dataset=header[0] if header else "",
                    metric=header[value_index] if metric_column >= 0 else "value",
                    condition=" | ".join(
                        f"{header[i]}={cells[i]}"
                        for i in range(1, min(value_index, len(cells)))
                        if i < len(header)
                    ),
                    method=method[:80],
                    value=cells[value_index],
                    row=row_index,
                    column=value_index,
                )
            )
    return records
