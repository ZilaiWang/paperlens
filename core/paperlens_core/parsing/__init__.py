"""Parser v2 (改进方案1 §三-五 / 改进方案2 §13-18).

Pipeline: DocumentProbe → ParsePlanner → ParserBackend → ParseCandidate →
Canonicalizer → RegionFusion → QualityInspector → RepairPlanner.

V1 ``parse_router.py`` remains the configured entry point used by the server;
this package is its structured successor and can be used directly by new code.
"""

from .benchmark import (
    BenchmarkDocument,
    BenchmarkEntry,
    BenchmarkReport,
    run_benchmark,
    run_benchmark_json,
)
from .candidates import CandidateKind, ParseCandidate
from .canonicalizer import Canonicalizer
from .contracts import (
    BackendProbe,
    BackendResult,
    Capability,
    ParserBackend,
    ParseRegion,
    ParseRequest,
)
from .fusion import FusionOutcome, RegionFusion
from .pipeline import ParsePipeline, PipelineResult
from .planner import ParsePlan, ParsePlanner, PlanStep
from .probe import DocumentProbe, ProbeReport
from .quality import ParseQualityReport, QualityInspector
from .repair import RepairPlan, RepairPlanner, RepairTarget

__all__ = [
    "BenchmarkDocument",
    "BenchmarkEntry",
    "BenchmarkReport",
    "run_benchmark",
    "run_benchmark_json",
    "CandidateKind",
    "ParseCandidate",
    "Canonicalizer",
    "BackendProbe",
    "BackendResult",
    "Capability",
    "ParseRegion",
    "ParseRequest",
    "ParserBackend",
    "FusionOutcome",
    "RegionFusion",
    "ParsePipeline",
    "PipelineResult",
    "ParsePlan",
    "ParsePlanner",
    "PlanStep",
    "DocumentProbe",
    "ProbeReport",
    "ParseQualityReport",
    "QualityInspector",
    "RepairPlan",
    "RepairPlanner",
    "RepairTarget",
]
