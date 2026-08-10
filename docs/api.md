# HTTP API

The FastAPI application exposes JSON resources under `/api` and Server-Sent
Events for long-running progress. When running locally, the generated OpenAPI UI
is available at `http://127.0.0.1:8700/docs` and the raw schema at
`http://127.0.0.1:8700/openapi.json`.

The generated schema is authoritative for request fields. This page explains
resource groups and behavioral conventions.

## Resource groups

| Group | Representative routes | Purpose |
| --- | --- | --- |
| Health | `GET /api/health` | Version and process health |
| Jobs | `GET /api/jobs/{id}`, `GET /api/jobs/{id}/events` | Import/parse progress and SSE |
| Papers | `/api/papers`, `/api/papers/{paper_id}` | Upload, arXiv import, list, inspect, delete |
| Document | outline, document, PDF, assets, callouts, page quality, metadata | Read persisted DocumentIR and source assets |
| Sessions | `/api/sessions` and message routes | Evidence-grounded conversations and streaming output |
| References | paper reference routes and `/api/references/{id}` | Extract, resolve, batch-check, and import citations |
| Analyses | method graph, experiments, profile, quality | Evidence-bound derived artifacts |
| Translations | `/api/papers/{paper_id}/translations` | Generate and read translation units |
| Comparisons | `/api/v1/comparisons` | Create, follow, query, and export cross-paper comparisons |
| Annotations | paper annotation routes | Store local highlights and notes |

## Identity rules

- `paper_id` identifies a logical paper.
- `version_id` identifies a concrete imported or parsed version.
- Evidence, blocks, chunks, translations, and comparisons belong to a version.
- Comparison requests therefore accept two or three `paper_version_ids`.

Do not substitute one identifier for the other even if a paper currently has
only one version.

## Jobs and events

Long operations return an identifier and a queued/running status rather than
holding the request open. Poll the resource or subscribe to its SSE endpoint.
Progress reflects completed pipeline stages rather than a time-based animation.

Clients should tolerate additional event types and response fields. SSE clients
must reconnect or fall back to polling after network interruption; the current
event bus is process-local and does not replay an unlimited history.

## Errors

FastAPI validation failures use HTTP 422. Domain and lookup errors use standard
4xx codes; upstream provider failures may use 5xx codes or be represented as a
failed background job. Clients should display both status and returned detail
without exposing credentials or entire document payloads in logs.

## Authentication and CORS

The 1.0 API has no authentication. Some routes accept `X-User-Id` or a
`user_id` field for local grouping, but these values are not trusted identity.
Development CORS is permissive. A public deployment must add authentication,
authorization, origin restrictions, TLS, rate limits, and request-size controls
at or before the API boundary.

## Compatibility policy

- Existing routes and fields should remain backwards compatible within 1.x.
- New optional response fields may be added.
- Semantic breaks require a new route version or a documented migration.
- Persisted evidence and version identity semantics are part of the contract.
- OpenAPI request-body presence is covered by regression tests for complex
  endpoints such as comparisons.

There is no separately published SDK yet. `web/lib/api.ts` is the current first-
party client. Generating a versioned SDK becomes worthwhile when external client
consumers appear.
