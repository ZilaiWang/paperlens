# Design decisions

This document records durable choices and the conditions that would justify
changing them. It is not an implementation diary.

## Deterministic structure before model interpretation

**Decision:** parse pages, blocks, sections, assets, and references before
calling a language model.

**Why:** document geometry and identity must survive model changes. It also
allows offline parsing tests and exact evidence navigation.

**Consequence:** unusual layouts and OCR remain explicit parser problems rather
than being hidden inside an opaque multimodal prompt.

## PyMuPDF plus pdfplumber

**Decision:** use a lightweight local dual-parser path, with PyMuPDF geometry as
the primary source and pdfplumber as fallback/fusion input.

**Why:** both run on modest hardware, expose useful page geometry, and avoid a
mandatory external parsing service.

**License boundary:** PyMuPDF is optional rather than a base dependency because
its upstream offers AGPL and commercial licensing. Users and distributors must
evaluate those terms for their use case; the default install can run on
pdfplumber alone.

**Revisit when:** a versioned corpus shows that Docling, GROBID, or another
backend materially improves target documents at an acceptable deployment cost.
Any new backend should implement the existing block and quality contracts.

## Source-first arXiv import

**Decision:** prefer structured arXiv HTML when available and fall back to PDF.

**Why:** LaTeXML preserves equation, bibliography, and section structure that is
difficult to recover from rendered pages.

**Consequence:** HTML papers do not have the same physical-page semantics as
PDFs. The product must expose provenance instead of pretending both sources are
identical.

## BM25 before vector retrieval

**Decision:** use a local paragraph-aware BM25 index as the default retriever.

**Why:** it is deterministic, inspectable, dependency-light, and adequate for a
single paper's scale.

**Revisit when:** a labeled retrieval benchmark demonstrates semantic recall
gaps. The preferred next step is hybrid retrieval with reciprocal-rank fusion,
not an unmeasured replacement.

## Typed workflows instead of a general agent runtime

**Decision:** implement Q&A, quality, profile, translation, and comparison as
bounded typed pipelines.

**Why:** each pipeline has known evidence inputs, schemas, network calls, and
failure modes. A general tool-calling loop would make attribution and cost less
predictable.

**Revisit when:** user-defined workflows become a real product requirement and
can be paired with permission, audit, versioning, and sandbox boundaries.

## SQLite and in-process jobs for 1.0

**Decision:** use SQLite, local files, threads, and in-process SSE events.

**Why:** this keeps self-hosting simple and matches the current single-process
usage model.

**Limit:** it does not support horizontal scaling, durable distributed jobs, or
strong tenant isolation.

**Migration trigger:** authentication plus multiple concurrent users, sustained
write contention, or the need to resume jobs after process failure. At that
point, move persistence, jobs, and events together rather than adding Uvicorn
workers to the current design.

## Descriptive comparison, not automatic winner selection

**Decision:** only compare numeric results when dataset, metric, and relevant
conditions align. Otherwise show a comparability warning.

**Why:** metric direction, evaluation protocol, and “our method” row detection
cannot be inferred safely from arbitrary table text.

## No wholesale OpenCode migration

**Decision:** borrow selected architectural practices from OpenCode but keep the
PaperLens Python/Next.js domain architecture.

**Why:** the products, runtimes, scale, and extension requirements are
different. PaperLens already has a useful core/server/client separation; a
rewrite would spend risk on language and framework migration without improving
PDF parsing or evidence quality.

The full assessment and adoption plan is in
[OpenCode assessment](opencode-assessment.md).
