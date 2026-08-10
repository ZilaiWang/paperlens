# Development

PaperLens is a Python/TypeScript monorepo with independent backend and frontend
toolchains. Keep changes within the narrowest owning layer and preserve the
evidence-location contract across layers.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e "core[server,dev]"
# Optional, for the enhanced parser path:
.venv/bin/pip install -e "core[pymupdf]"

cd web
bun install --frozen-lockfile
```

## Repository responsibilities

| Path | Owns | Must not own |
| --- | --- | --- |
| `core/paperlens_core/` | Domain models, parsing, retrieval, evidence validation, analysis workflows | FastAPI requests, browser state, deployment paths |
| `server/app/` | HTTP transport, request schemas, persistence adapters, job orchestration | PDF parsing heuristics or UI behavior |
| `web/` | Reader interaction, presentation, API client types | Evidence truth or backend-only business rules |
| `scripts/` | Reproducible evaluation and release utilities | Product runtime behavior |
| `tests/` | Offline regression and contract tests | Mutable production data |

New request models belong in `server/app/schemas.py`. Reusable application
orchestration belongs in `server/app/services/`; route functions should remain
transport adapters. New domain behavior belongs in the core package and should
be callable without FastAPI.

## Quality gates

Run from the repository root:

```bash
.venv/bin/ruff check core server scripts tests
.venv/bin/python -m pytest
cd web && bun run build
```

The same checks run in CI. Add focused regression tests for every bug fix. Mock
network and LLM boundaries so the default test suite remains deterministic.

## Compatibility

- Python 3.10 is the minimum supported runtime. Do not introduce 3.11-only
  standard-library APIs without a compatibility path.
- Public HTTP routes live under `/api`. Avoid breaking response shapes. Add
  fields compatibly, or introduce a new versioned route when semantics change.
- Persisted `DocumentIR` shapes require explicit migration or backwards-
  compatible parsing. Never silently reinterpret stored evidence coordinates.
- Frontend API types in `web/lib/api.ts` should match OpenAPI response models.

## Code organization policy

Do not create a new package merely to reduce line count. Extract a module when
it has an independent responsibility, stable inputs/outputs, or more than one
consumer. Conversely, route files and UI components above roughly 500 lines are
a signal to look for coherent domains that can be separated and tested.

The next structural targets are documented in [Roadmap](roadmap.md). In
particular, the API composition module and the two largest React components
should be split by feature, while the stable core imports remain compatible.

## Database changes

`server/app/repository.py` currently owns SQLite schema setup and lightweight
in-place migrations. A schema change must:

1. preserve existing local databases;
2. include a repository test covering old and new shapes;
3. remain safe when the process restarts during migration;
4. update architecture and configuration documentation when operational
   behavior changes.

Do not edit `.paperlens/paperlens.db` as part of development changes.

## Dependency changes

- Backend runtime dependencies belong in `core/pyproject.toml`.
- API-only dependencies belong in the `server` optional dependency group.
- Dependencies with materially different licensing, such as PyMuPDF, belong in
  an explicit optional group and require a notice update.
- Frontend dependencies belong in `web/package.json` and must update
  `web/bun.lock`.
- Prefer a small dependency surface. Parsing and evidence rules should not
  depend on a general agent framework when a typed function is sufficient.

## Documentation changes

Update the document that owns the changed behavior. Avoid dated implementation
diaries in active docs; durable decisions belong in
[Design decisions](design-decisions.md), release changes in the
[Changelog](../CHANGELOG.md), and future work in [Roadmap](roadmap.md).
