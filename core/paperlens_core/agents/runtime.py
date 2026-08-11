"""Tool runtime: registered, typed tools (改进方案2 Phase H §46)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field


class ToolContext(BaseModel):
    """Inputs every tool can rely on."""

    model_config = ConfigDict(extra="allow")

    workspace_id: str = ""
    project_id: str = ""
    run_id: str = ""
    question: str = ""
    params: dict[str, object] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Structured tool output."""

    model_config = ConfigDict(extra="allow")

    ok: bool = True
    data: dict[str, object] = Field(default_factory=dict)
    error: str = ""
    meta: dict[str, object] = Field(default_factory=dict)


# A handler receives ToolContext and returns ToolResult (or a dict).
ToolHandler = Callable[[ToolContext], ToolResult | dict[str, object]]


@dataclass
class ToolSpec:
    name: str
    description: str
    handler: ToolHandler


class ToolRegistry:
    """Named tool registry; tools are looked up by the executor."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def invoke(
        self,
        name: str,
        context: ToolContext,
    ) -> ToolResult:
        spec = self.get(name)
        if spec is None:
            return ToolResult(ok=False, error=f"tool not found: {name}")
        try:
            result = spec.handler(context)
            if isinstance(result, ToolResult):
                return result
            return ToolResult(data=dict(result or {}))
        except Exception as exc:  # noqa: BLE001 - tool errors are data
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")


def make_tool(
    name: str,
    description: str,
) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator to register a tool at import time."""

    def decorator(handler: ToolHandler) -> ToolHandler:
        ToolRegistry().register(ToolSpec(name, description, handler))
        return handler

    return decorator
