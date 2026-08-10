<div align="center">

# PaperLens

**An evidence-grounded workspace for reading and comparing research papers.**

Upload a PDF or import an arXiv paper, then read, translate, ask questions,
inspect citations, and compare papers without losing the path back to the source.

[简体中文](README.zh-CN.md) · [Documentation](docs/README.md) ·
[Contributing](CONTRIBUTING.md) · [Roadmap](docs/roadmap.md)

[![CI](https://github.com/ZilaiWang/paperlens/actions/workflows/ci.yml/badge.svg)](https://github.com/ZilaiWang/paperlens/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](core/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

</div>

## Why PaperLens?

Academic PDFs are not plain text. Reading order, columns, equations, tables,
citations, and page geometry all matter. Sending an entire PDF directly to a
language model often destroys that structure and makes answers difficult to
verify.

PaperLens first builds a deterministic document representation. Retrieval and
language-model workflows operate on that representation, and evidence links
connect generated claims back to exact blocks, character spans, pages, and PDF
coordinates.

## What it can do

- **Structured import:** upload PDF files or import arXiv papers. Modern arXiv
  pages use structured HTML first; PDF parsing remains the fallback.
- **Layout-aware parsing:** combine PyMuPDF geometry with pdfplumber fallback,
  reconstruct multi-column paragraphs, detect sections, and preserve media and
  formula placeholders.
- **Bilingual reading:** translate incrementally with terminology, citation,
  number, and formula protection.
- **Grounded Q&A:** retrieve paragraph-level evidence with BM25, draft atomic
  claims, run deterministic and model-based attribution checks, then link every
  accepted claim to its source.
- **Paper analysis:** build method graphs, structured experiment records,
  evidence-bound profiles, and quality assessments.
- **Cross-paper comparison:** compare two or three paper versions, distinguish
  missing evidence from confirmed absence, and avoid ranking incomparable
  metrics or datasets.
- **Reference workflow:** extract references, lint citation formatting, resolve
  identities through scholarly APIs, and import public arXiv sources.

## Quick start

### Requirements

- Python 3.10 or newer
- [Bun](https://bun.sh/) 1.3 or newer
- An OpenAI-compatible chat-completions endpoint for translation and analysis
  features; parsing and offline tests do not require a model

### Run locally

```bash
git clone https://github.com/ZilaiWang/paperlens.git
cd paperlens

python3 -m venv .venv
.venv/bin/pip install -e "core[server,dev]"
# Optional enhanced geometry/table path; review its AGPL/commercial license.
.venv/bin/pip install -e "core[pymupdf]"
cp .env.example .env
.venv/bin/uvicorn server.app.main:app --reload --port 8700
```

In a second terminal:

```bash
cd web
bun install --frozen-lockfile
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8700 bun run dev
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000). The API schema is
available at [http://127.0.0.1:8700/docs](http://127.0.0.1:8700/docs).

The default `.env.example` points to a local OpenAI-compatible endpoint. Update
`OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `PAPERLENS_MODEL` for your provider.
See the [configuration reference](docs/configuration.md) for every supported
setting.

## Architecture

```mermaid
flowchart LR
    UI["Next.js web"] --> API["FastAPI API"]
    API --> JOBS["Jobs and SSE events"]
    JOBS --> CORE["paperlens_core"]
    CORE --> IR["DocumentIR"]
    IR --> RETRIEVAL["BM25 and evidence ledger"]
    RETRIEVAL --> LLM["Bounded LLM workflows"]
    API --> DB["SQLite and local files"]
```

The repository is a small polyglot monorepo:

```text
core/       Python domain library: parsing, DocumentIR, retrieval, analysis
server/     FastAPI transport, persistence adapters, jobs, and application services
web/        Next.js reader and comparison interface
scripts/    Reproducible evaluation and release utilities
tests/      Offline regression tests and downloadable corpus manifest
docs/       User, operator, contributor, architecture, and decision documentation
```

Read [Architecture](docs/architecture.md) for data flow, module boundaries, and
the rules intended to keep the project evolvable.

## Development

```bash
.venv/bin/ruff check core server scripts tests
.venv/bin/python -m pytest
cd web && bun run build
```

The evaluation PDFs are intentionally not stored in Git. Download and verify
them from the checked-in manifest when needed:

```bash
.venv/bin/python scripts/fetch_eval_corpus.py
.venv/bin/python scripts/eval_parse.py --corpus tests/eval_corpus
```

See [Development](docs/development.md), [Testing](docs/testing.md), and
[Contributing](CONTRIBUTING.md) before opening a pull request.

## Project status and limitations

PaperLens 1.0 is usable as a self-hosted, single-process application. It is not
yet a multi-tenant cloud service. SQLite, in-process jobs, permissive development
CORS, and the absence of built-in authentication are deliberate current
constraints. Do not expose the API directly to the public internet without an
authentication layer and a restrictive reverse-proxy configuration.

Complex borderless tables, scanned PDFs, formula OCR, and unusual multi-column
layouts can still produce partial parses. PaperLens reports parse and evidence
gaps rather than treating missing extraction as proof that a paper omitted
something.

See [Roadmap](docs/roadmap.md) for the planned modularization and scaling path.

## Community and security

- Use [GitHub Issues](https://github.com/ZilaiWang/paperlens/issues) for bugs and
  feature proposals.
- Read [SECURITY.md](SECURITY.md) before reporting a vulnerability.
- Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

PaperLens is released under the [MIT License](LICENSE). Papers imported by users
remain subject to their original licenses and terms; PaperLens does not grant
redistribution rights for third-party documents. Optional PyMuPDF support is
dual-licensed under AGPL/commercial terms; review
[third-party notices](THIRD_PARTY_NOTICES.md) before distribution or hosted use.
