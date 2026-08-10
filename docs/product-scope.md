# Product scope

PaperLens helps a reader inspect one or a few academic papers while preserving
evidence traceability. It is designed for self-hosted research and learning
workflows, not as a publisher database or autonomous literature-review system.

## Supported workflows

### Import and understand

- Upload a text-based PDF.
- Import an arXiv identifier or URL.
- Recover reading order, paragraphs, sections, formulas, tables, figures,
  references, and page-quality signals where the source permits.
- Preserve source provenance and version identity.

### Read and translate

- Browse a structured reading view or original PDF view.
- Navigate the outline, assets, citations, and references.
- Translate progressively while protecting formulas, citations, and terminology.

### Ask and analyze

- Ask evidence-grounded questions over a whole paper or selected context.
- Inspect the evidence used for accepted claims.
- Build method, experiment, profile, and quality artifacts.
- Store sessions and annotations locally.

### Compare and verify

- Compare two or three specific paper versions.
- Extract configured dimensions independently per paper.
- Show source excerpts and locators.
- Mark incompatible datasets, metrics, or conditions.
- Export comparison results and ask evidence-bound follow-up questions.
- Extract, lint, resolve, and import references where a public source exists.

## Current non-goals

- Multi-tenant SaaS, organization accounts, billing, or public deployment.
- OCR for scanned documents.
- Guaranteed extraction from arbitrary tables, mathematical layouts, or broken
  PDFs.
- Circumventing paywalls or redistributing papers.
- Exhaustive systematic-review search across publisher indexes.
- Automatic claims that one paper is universally “better” than another.
- An unrestricted autonomous agent, user-installed runtime plugins, or remote
  code execution.
- Medical, legal, or other high-stakes decisions based solely on generated
  summaries.

## Quality principles

1. Evidence identity is more important than fluent prose.
2. Missing extraction and confirmed absence are different states.
3. Deterministic checks should guard model output where possible.
4. Provenance must remain visible across PDF and HTML import paths.
5. Offline parsing and regression tests must work without model credentials.
6. Product claims in documentation should be reproducible or explicitly scoped.
