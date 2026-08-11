"""Comparison v2 (改进方案1 §十 / 改进方案2 Phase F §32-38).

V1 ``comparison.py`` compared a fixed question across papers in one call.
v2 introduces the persistent ``ComparisonSet``:

    ComparisonSet (a saved comparison project)
        ├── papers[]
        ├── dimensions[]   (built-in + user-defined extraction dimensions)
        ├── cells[]        (dimension x paper ResultRecord)
        └── synthesis      (gap analysis / consensus / contradiction)

The old inline-comparison flow remains the "quick compare" entry point; the
v2 flow is save-able, re-runnable and grows a custom extraction dimension.
"""

from .alignment import AlignedRow, AlignedTable, align_results, align_results_row
from .comparability import (
    ComparabilityKey,
    ResultRecord,
    result_record_from_profile,
)
from .extraction import (
    CustomDimension,
    CustomDimensionResult,
    extract_custom_dimensions,
)
from .models import (
    ComparisonCell,
    ComparisonSet,
    ComparisonStatus,
    ComparisonSynthesis,
    ComparisonVersion,
)
from .synthesis import (
    ConsensusFinder,
    GapAnalysis,
    Synthesizer,
)

__all__ = [
    "AlignedRow",
    "AlignedTable",
    "align_results",
    "align_results_row",
    "ComparabilityKey",
    "ResultRecord",
    "result_record_from_profile",
    "CustomDimension",
    "CustomDimensionResult",
    "extract_custom_dimensions",
    "ComparisonCell",
    "ComparisonSet",
    "ComparisonSynthesis",
    "ComparisonStatus",
    "ComparisonVersion",
    "ConsensusFinder",
    "GapAnalysis",
    "Synthesizer",
]
