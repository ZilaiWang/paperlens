# Changelog

Notable user-facing changes are documented here. PaperLens follows
[Semantic Versioning](https://semver.org/) from 1.0.0 onward.

## [Unreleased]

## [1.2.0] - 2026-08-11

### Added

- Added canonical DocumentIR revisions and provenance, multi-backend parser
  planning/fusion/repair, parse benchmarks, and persisted canonical documents.
- Added a workspace-scoped v2 API, layered terminology and translation memory,
  translation verification/repair, comparison sets, custom dimensions, and
  reproducible Research Agent task DAGs.
- Added an anonymous-by-default workspace identity with opaque HttpOnly sessions
  and storage-level isolation.
- Added a paper library that can launch multi-paper comparison directly from a
  selected reading set.

### Changed

- Rebuilt the web interface around the single-paper reader: the reader now owns
  translation, paper analysis, evidence Q&A, and contextual comparison actions.
- Moved terminology into translation settings instead of presenting it as a
  primary product area, and removed research projects from the main navigation.
- Reworked the paper reader, library, assistant, and global shell into one warm,
  consistent visual system with a reading-first default layout.
- Reorganized public documentation into task-focused guides with English and
  Simplified Chinese landing pages.
- Added contributor, security, conduct, citation, pull-request, and repository
  architecture guidance.
- Centralized FastAPI request schemas and comparison application adapters.
- Unified project version reporting and backend installation extras.
- Added Python linting and reproducible Bun installation to CI.

### Fixed

- Replaced client-selected workspace IDs with opaque HttpOnly sessions and
  isolated terminology and translation memory by workspace.
- Prevented vNext tests from mutating the user's local database or reading
  private uploaded PDFs.
- Fixed project-paper request parsing, repeated-node identity collisions,
  parser region loss, translation placeholder verification, invalid TM writes,
  custom comparison synthesis, and Agent report ordering/status.
- Restored the comparison endpoint's JSON request-body schema.
- Restored comparison artifact-field reuse and batch cell translation adapters.
- Fixed deferred reference-import jobs capturing loop variables incorrectly.
- Fixed shared SQLite connection races, empty comparison claims, real-PDF page
  access in research runs, translation placeholder restoration, and workspace
  authorization failures under concurrent requests.

### Removed

- Removed unintegrated memory/tool experiments and obsolete demo CLI commands.
- Removed duplicate and historical audit documents from the active docs set.
- Removed downloadable evaluation PDFs from the Git tree; the checked-in
  manifest and downloader remain the reproducible source.

## [1.0.0] - 2026-08-07

First public release.

### Added

- PDF and source-first arXiv import with layout-aware parsing and page-quality
  fusion.
- DocumentIR blocks, sections, assets, formulas, references, chunks, and stable
  evidence locators.
- Structured reader, original-PDF mode, progressive translation, and protected
  terminology/citation/formula handling.
- BM25 evidence retrieval, claim validation, semantic attribution, and streamed
  grounded Q&A.
- Method graphs, experiment records, evidence-bound paper profiles, and quality
  assessment.
- Two-to-three-paper comparison with topic alignment, structured fields,
  comparability warnings, evidence locators, export, and follow-up questions.
- Reference extraction, formatting checks, scholarly identity resolution, batch
  progress, and public arXiv import.
- Offline regression tests, parser corpus manifest, and source-release hygiene
  checks.
