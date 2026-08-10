# OpenCode architecture assessment

## Recommendation

Do **not** migrate PaperLens onto the OpenCode codebase or rewrite it into
OpenCode's TypeScript/Bun architecture now.

Borrow four patterns instead:

1. keep a clean client/server boundary;
2. make OpenAPI the machine-readable API contract;
3. organize a monorepo by independently owned products and packages;
4. document dependency direction and local agent instructions close to code.

PaperLens already has the first version of these boundaries. The highest-value
work is to finish them incrementally, not restart the product.

## What OpenCode is optimized for

OpenCode is a large, actively developed coding-agent platform. Its repository is
a Bun workspace with many packages for a CLI/TUI, shared app UI, desktop app,
server, SDKs, protocol, schemas, plugins, infrastructure, and integrations. Its
headless server publishes OpenAPI 3.1, and clients—including the TUI—communicate
through that server. Public protocol changes can regenerate client artifacts.

Those choices fit a product with many clients, extension surfaces, providers,
and a very large contributor base. They also carry substantial complexity:
workspace dependency rules, code generation, multiple runtimes, protocol
versioning, plugin compatibility, desktop packaging, and a broad release matrix.

## How PaperLens differs

| Concern | PaperLens | OpenCode-style platform |
| --- | --- | --- |
| Primary domain | PDF structure, evidence, scholarly workflows | Coding sessions, tools, files, agents, IDE/TUI clients |
| Core runtime | Python scientific/document ecosystem | TypeScript/Bun application ecosystem |
| Clients | One Next.js web app | TUI, web, desktop, IDE, SDK, integrations |
| Extension demand | No stable third-party plugin ecosystem yet | Plugins, tools, providers, agents, MCP, SDKs |
| Deployment today | Single-process self-hosted app | Multiple product/client distribution modes |
| Hard problem | Parse quality and evidence correctness | Agent orchestration and developer tooling |

A wholesale migration would require rewriting mature parsing, scholarly, and
evidence code or operating a permanent two-language bridge. It would not, by
itself, improve table extraction, OCR, retrieval recall, or evidence quality.

## Patterns worth adopting now

### API-first client/server boundary

OpenCode's server publishes an OpenAPI endpoint used by clients and SDKs. For
PaperLens, keep FastAPI as the contract owner, strengthen response schemas, test
the generated spec, and eventually generate frontend types. The current web/API
separation already makes this an incremental change.

### Explicit dependency direction

OpenCode documents which packages may depend on schema, protocol, core, server,
and clients. PaperLens should enforce the simpler equivalent:

```text
documents/domain -> workflows -> application services -> HTTP routes
                         ^                ^
                  provider adapters   persistence adapters

web client -> OpenAPI contract -> HTTP routes
```

Core never imports the server; server routes do not own parsing heuristics; the
web app does not decide evidence truth.

### Workspace-level commands

OpenCode offers clear root commands for linting and type checking. PaperLens now
has root Python tool configuration; the next incremental improvement is a small
cross-language task runner or documented `make`/`just` commands for install,
dev, lint, test, and build. Do not add a monorepo orchestrator until command or
caching complexity justifies it.

### Package only at real boundaries

OpenCode's package count reflects many separately shipped products. PaperLens
should not imitate the count. Keep `core`, `server`, and `web` as top-level
ownership boundaries. Inside Python, use subpackages only when parsing,
evidence, scholarly, or analysis modules need independent public APIs.

## Patterns to defer

- Plugin runtime and marketplace
- Generated SDK package
- Desktop/TUI clients
- Protocol package separate from OpenAPI/Pydantic schemas
- Bun workspace migration for the Python core
- Microservices or distributed infrastructure

Each becomes reasonable only when an observed consumer or bottleneck exists.

## Incremental adoption plan

### Phase 1: current repository

- Keep request schemas outside route implementations.
- Move coherent orchestration into application services.
- Split the API entrypoint by feature routers without changing URLs.
- Add OpenAPI contract tests and align `web/lib/api.ts`.
- Keep one root documentation index and concise contributor instructions.

### Phase 2: multiple clients or external integrations

- Stabilize and version OpenAPI response models.
- Generate a TypeScript client and use it in `web`.
- Publish the client only if external consumers need it.
- Introduce event replay/durable jobs before adding more API processes.

### Phase 3: external extensions

- Collect at least two real extension implementations.
- Extract the common provider/parser/analysis interface.
- Define permissions, network policy, compatibility, provenance, and failure
  isolation before calling the interface a plugin system.

## Migration trigger

Reconsider a deeper architectural migration only if PaperLens becomes a
multi-client platform whose main engineering cost is client/protocol/plugin
coordination rather than document understanding. Even then, preserve the Python
document core as a service or library unless measured evidence supports a
rewrite.

## Sources reviewed

- [OpenCode repository](https://github.com/anomalyco/opencode)
- [OpenCode server documentation](https://opencode.ai/docs/server/)
- [OpenCode contributing guide](https://github.com/anomalyco/opencode/blob/dev/CONTRIBUTING.md)
- [OpenCode workspace manifest](https://github.com/anomalyco/opencode/blob/dev/package.json)
