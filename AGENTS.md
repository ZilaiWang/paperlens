# Repository guidance

PaperLens is a Python/Next.js monorepo. Preserve these ownership boundaries:

- `core/paperlens_core`: document domain, parsing, retrieval, evidence, and
  model workflows. It must not import `server`.
- `server/app`: FastAPI transport, request schemas, persistence, jobs, and
  application services. Request models belong in `schemas.py`; reusable route
  orchestration belongs in `services/`.
- `web`: presentation and browser interaction. Evidence support decisions stay
  on the backend.
- `scripts`: reproducible evaluation/release utilities, never product runtime.
- `tests`: offline by default; use temporary data and deterministic model fakes.

Run before handoff:

```bash
.venv/bin/ruff check core server scripts tests
.venv/bin/python -m pytest
cd web && bun run build
```

Never commit `.env`, `.paperlens/`, downloaded corpus PDFs, databases, logs,
credentials, or private paper content. Preserve `paper_version_id` ownership for
blocks, chunks, translations, and evidence. Treat missing extraction and
confirmed absence as different states.

See `docs/development.md` and `docs/architecture.md` for the full rules. The
`web/AGENTS.md` file adds version-specific Next.js guidance.
