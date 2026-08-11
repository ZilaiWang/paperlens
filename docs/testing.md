# Testing

PaperLens separates fast offline regression tests from the downloadable parser
evaluation corpus. The default suite must not require network access, API keys,
or third-party PDFs.

## Offline suite

```bash
.venv/bin/python -m pytest
```

The suite covers document schemas, section and paragraph reconstruction,
quality-gate fusion, translation protection, evidence validation, reference
parsing and resolution adapters, API contracts, and selected endpoint behavior.

For a focused run:

```bash
.venv/bin/python -m pytest tests/test_server_contracts.py
.venv/bin/python -m pytest tests/test_references.py -k lint
```

## Static checks

```bash
.venv/bin/ruff check core server scripts tests
cd web && bun run build
```

The frontend production build is the current TypeScript correctness gate.

## Parser evaluation corpus

Only `tests/eval_corpus/manifest.json` is stored in Git. Each entry records an
arXiv source and SHA-256 checksum. Download the files when parser evaluation is
needed:

```bash
.venv/bin/python scripts/fetch_eval_corpus.py --dir tests/eval_corpus
.venv/bin/python scripts/eval_parse.py --corpus tests/eval_corpus
PYTHONPATH=core .venv/bin/python scripts/parser_bench.py path/to/local-manifest.json
PYTHONPATH=core .venv/bin/python scripts/agent_bench.py
```

Downloaded PDFs are ignored by Git. Do not add them to commits or release
archives.

ParserBench records repair passes, backend errors, and paragraph/order/table/
formula/reference quality in addition to aggregate coverage. AgentBench checks
depth/intent routing, unique task IDs, and the 3–8 task bound. Treat checked-in result snapshots
as historical baselines, not universal quality guarantees: parser outcomes vary
with dependency versions and the document set is small.

## Test design rules

- A bug fix requires a test that fails for the original behavior.
- Use `StaticJSONModel` or a narrow fake at model boundaries.
- Mock HTTP at the scholarly/arXiv client boundary, not inside parsing logic.
- Assert evidence IDs, paper-version ownership, and locators when testing
  generated claims or comparisons.
- Distinguish `NOT_FOUND_IN_SEARCHED_SECTIONS`,
  `NOT_REPORTED_CONFIRMED`, and parse gaps.
- Use temporary directories and SQLite databases. Never depend on `.paperlens/`.

## Before a release

```bash
.venv/bin/ruff check core server scripts tests
.venv/bin/python -m pytest
(cd web && bun install --frozen-lockfile && bun run build)
.venv/bin/python scripts/package_release.py --check
```

Also import at least one PDF and one arXiv paper in a clean environment, then
exercise reading, Q&A, translation, reference listing, and comparison manually.
