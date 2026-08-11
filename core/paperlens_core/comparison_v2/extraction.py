"""Custom extraction dimensions (改进方案2 Phase F §33 [3][4]).

Built-in dimensions (problem/method/experiments/result_summary) come from the
PaperProfile.  A ``CustomDimension`` is a user-defined question asked of each
paper; results are stored in the ComparisonSet and re-extractable.
"""

from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, ConfigDict, Field

from ..papers.models import PaperProfile


class CustomDimension(BaseModel):
    """A user-defined extraction dimension."""

    model_config = ConfigDict(extra="allow")

    dimension_id: str = ""
    name: str
    instruction: str = ""       # what to extract
    created_at: str = ""
    version: str = "1"


class CustomDimensionResult(BaseModel):
    """Extraction output for one paper for one custom dimension."""

    model_config = ConfigDict(extra="allow")

    dimension_id: str
    paper_version_id: str
    value: object = None
    quote: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw_payload: dict[str, object] = Field(default_factory=dict)


def extract_custom_dimensions(
    dimensions: list[CustomDimension],
    profiles: list[PaperProfile],
    *,
    extractor: Callable[[CustomDimension, PaperProfile], CustomDimensionResult] | None = None,
    model: object | None = None,
    stage: str = "custom_dimension_extract",
    thread_id: str = "",
) -> list[CustomDimensionResult]:
    """Extract custom dimensions across papers.

    If ``extractor`` is given, it is called per (dimension, paper); otherwise
    a default LLM-driven extractor is used (skipping when no model).
    """
    results: list[CustomDimensionResult] = []
    for dimension in dimensions:
        for profile in profiles:
            if extractor is not None:
                result = extractor(dimension, profile)
            else:
                result = _llm_extract(
                    dimension,
                    profile,
                    model=model,
                    stage=stage,
                    thread_id=thread_id,
                )
            if result is not None:
                results.append(result)
    return results


def _llm_extract(
    dimension: CustomDimension,
    profile: PaperProfile,
    *,
    model: object | None,
    stage: str,
    thread_id: str,
) -> CustomDimensionResult | None:
    if model is None:
        return None
    schema = _DimensionResult
    response = model.invoke_json(
        system=(
            "Extract one structured answer for the dimension instruction from "
            "the paper profile. Return JSON with value/quote/confidence."
        ),
        user=(
            f"DIMENSION: {dimension.name}\nINSTRUCTION: {dimension.instruction}\n"
            f"PAPER:\n{profile.summary()[:2000]}"
        ),
        schema=schema,
        stage=stage,
        thread_id=thread_id,
    )
    return CustomDimensionResult(
        dimension_id=dimension.dimension_id or dimension.name,
        paper_version_id=profile.paper_version_id,
        value=response.value,
        quote=response.quote,
        confidence=response.confidence,
    )


class _DimensionResult(BaseModel):
    value: object = None
    quote: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
