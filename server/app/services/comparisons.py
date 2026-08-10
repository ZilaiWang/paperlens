"""Adapters shared by the comparison API workflow."""

from __future__ import annotations

from paperlens_core.comparison import ComparisonCell, translate_cell_values_zh
from paperlens_core.llm import StructuredModel

ARTIFACT_FIELD_MAP = {
    "task_definition": "task",
    "method_core": "method",
    "datasets_and_samples": "datasets",
    "training_setup": "protocols",
    "inference_setup": "protocols",
    "metrics": "metrics",
    "main_results": "main_results",
    "ablations": "ablations",
    "code_and_data": "reproducibility",
    "author_limitations": "limitations",
}


def translate_comparison_cells(
    model: StructuredModel, cells: list[ComparisonCell]
) -> dict[str, str]:
    """Translate populated cells while preserving a stable paper/field key."""
    items = {
        f"{cell.paper_id}|{cell.field}": cell.value
        for cell in cells
        if cell.value.strip()
    }
    return translate_cell_values_zh(model, items)
