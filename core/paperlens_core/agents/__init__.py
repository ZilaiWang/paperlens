"""Research Agent (改进方案1 §十五-十六 / 改进方案2 Phase H §44-47).

The agent is *not* an unstructured chat loop.  A ResearchRun is a DAG of
typed tasks (plan → retrieve → synthesize → produce), executed by a real
TaskRuntime.  Tools are registered capabilities (search, compare, profile);
their inputs/outputs are data, not text soup.
"""

from .executor import execute_run, run_dag
from .models import (
    ArtifactProduced,
    ResearchRun,
    RunStatus,
    TaskDefinition,
    TaskDependency,
    TaskResult,
    TaskStatus,
)
from .planner import TaskPlanner, create_run_plan
from .runtime import (
    ToolContext,
    ToolHandler,
    ToolRegistry,
)
from .tools import (
    build_default_registry,
)

__all__ = [
    "execute_run",
    "run_dag",
    "ArtifactProduced",
    "ResearchRun",
    "RunStatus",
    "TaskDependency",
    "TaskDefinition",
    "TaskResult",
    "TaskStatus",
    "TaskPlanner",
    "create_run_plan",
    "ToolContext",
    "ToolHandler",
    "ToolRegistry",
    "build_default_registry",
]
