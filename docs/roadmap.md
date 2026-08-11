# Roadmap

The roadmap is ordered by architectural pressure and user value, not promised
dates. Open an issue before implementing a large item so requirements and
compatibility can be discussed first.

## Now: stabilize the open-source foundation

- Keep CI authoritative for Python lint, offline tests, and frontend builds.
- Add endpoint contract coverage for under-tested analysis and comparison paths.
- Split `server/app/main.py` into feature routers with injected services while
  preserving every existing URL and response shape.
- Split the largest frontend components by feature state and view ownership.
- Generate or validate frontend API types from the FastAPI OpenAPI schema.
- Establish repeatable release tags and keep one source of truth for versioning.

## Next: measure Parser v2 and Paper Agent quality

- Expand the parser corpus with legally redistributable or manifest-downloaded
  examples and explicit layout labels.
- Measure section, paragraph, table, formula, reference, and reading-order accuracy.
- Expand Docling/GROBID/PaddleOCR-VL provider fixtures and deployment recipes.
- Label difficult pages and AgentBench question/evidence expectations.
- Build a labeled retrieval benchmark, then evaluate BM25 plus semantic hybrid
  retrieval and reciprocal-rank fusion.

## Then: make jobs and storage durable

- Introduce explicit schema migrations.
- Move long-running jobs and events out of process before enabling multiple API
  workers.
- Add PostgreSQL only when queryability, concurrency, or tenant isolation needs
  justify the operational cost.
- Add cancellation, retry policy, idempotency, and resumable job semantics.
- Define data-retention and verified deletion workflows.

## Later: multi-user and extension boundaries

- Add authentication, authorization, restrictive CORS, rate limits, and tenant
  ownership before public hosting.
- Publish a stable OpenAPI contract and generated client package if external
  clients appear.
- Define provider adapters for model, metadata, parser, and storage boundaries.
- Consider plugins only after multiple external extensions need the same stable
  contract; include permission, compatibility, audit, and sandbox design from
  the beginning.

## Explicitly deferred

- Rewriting PaperLens on the OpenCode codebase or TypeScript stack.
- A general-purpose coding-agent runtime.
- Research Project, Hypothesis Board, Experiment Center, and AutoResearch as
  primary product surfaces.
- A terminology-management SaaS; term packs remain versioned reader assets.
- Automatic leaderboard-style winner selection across incomparable papers.
- Microservices before the single-process bottlenecks are measured.

See [OpenCode assessment](opencode-assessment.md) for the migration decision and
[Design decisions](design-decisions.md) for the reasoning behind current choices.
