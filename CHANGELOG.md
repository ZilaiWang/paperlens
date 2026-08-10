# Changelog

Notable user-facing changes are documented here. PaperLens follows
[Semantic Versioning](https://semver.org/) from 1.0.0 onward.

## [Unreleased]

### Changed

- Reorganized public documentation into task-focused guides with English and
  Simplified Chinese landing pages.
- Added contributor, security, conduct, citation, pull-request, and repository
  architecture guidance.
- Centralized FastAPI request schemas and comparison application adapters.
- Unified project version reporting and backend installation extras.
- Added Python linting and reproducible Bun installation to CI.

### Fixed

- Restored the comparison endpoint's JSON request-body schema.
- Restored comparison artifact-field reuse and batch cell translation adapters.
- Fixed deferred reference-import jobs capturing loop variables incorrectly.

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
