"""vNext repositories.

The V1 ``repository.py`` stays as-is (compat).  This package adds the
VNextRepository — workspace-scoped storage for projects, research graph,
comparison sets, research runs, termbase and translation memory, on the same
SQLite file (WAL allows concurrent connections).
"""

from .vnext import VNextRepository

__all__ = ["VNextRepository"]
