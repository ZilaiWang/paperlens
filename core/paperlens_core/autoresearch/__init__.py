"""AutoResearch Bridge (改进方案1 §二十六 / 改进方案2 Phase I §48-50).

Pack the research workspace context into a portable ResearchContextPack and
record experiment runs.  The bridge keeps a clear boundary: PaperLens owns
the context, the external execution owns the run; results flow back as
ResultAnalysis records.
"""

from .context import (
    ResearchContextPack,
    build_research_context_pack,
    pack_from_project,
)
from .experiment import (
    ExperimentPlan,
    ExperimentRun,
    ResultAnalysis,
    analyze_run_results,
    create_experiment_run,
)

__all__ = [
    "ResearchContextPack",
    "build_research_context_pack",
    "pack_from_project",
    "ExperimentPlan",
    "ExperimentRun",
    "ResultAnalysis",
    "create_experiment_run",
    "analyze_run_results",
]
