"""Research Workspace (改进方案1 §十二-十四 / 改进方案2 Phase G §39-43).

Project is the top-level research container.  ResearchGraph holds the
growing web of questions / insights / hypotheses / papers.  Artifacts are
the outputs the user keeps (notes, comparisons, reports).
"""

from .artifacts import (
    ArtifactKind,
    ResearchArtifact,
    artifact_from_text,
)
from .graph import (
    ResearchEdge,
    ResearchEdgeType,
    ResearchGraph,
    ResearchNode,
    ResearchNodeType,
)
from .models import (
    Hypothesis,
    HypothesisStatus,
    Insight,
    Project,
    ProjectStatus,
    ResearchQuestion,
    ResearchQuestionStatus,
)

__all__ = [
    "ArtifactKind",
    "ResearchArtifact",
    "artifact_from_text",
    "ResearchEdge",
    "ResearchEdgeType",
    "ResearchGraph",
    "ResearchNode",
    "ResearchNodeType",
    "Hypothesis",
    "HypothesisStatus",
    "Insight",
    "Project",
    "ProjectStatus",
    "ResearchQuestion",
    "ResearchQuestionStatus",
]
