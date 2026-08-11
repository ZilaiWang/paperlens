"""vNext routers, mounted onto the V1 app in main.py.

Keeping them as separate APIRouters lets the V1 main.py stay the composition
root while new capabilities (workspace, projects, comparison sets, research
runs, termbase, memory) live in cleanly separated files.
"""

from .vnext import router as vnext_router

__all__ = ["vnext_router"]
