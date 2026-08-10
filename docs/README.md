# PaperLens documentation

This directory is the source of truth for using, operating, and extending
PaperLens. The root [README](../README.md) is intentionally short; details live
here so they can evolve without turning the project landing page into a manual.

## Start here

| Document | Audience | Purpose |
| --- | --- | --- |
| [Getting started](getting-started.md) | Users | Install PaperLens and import a first paper |
| [Configuration](configuration.md) | Users, operators | Model, parser, storage, quota, and proxy settings |
| [Architecture](architecture.md) | Contributors | Data flow, boundaries, persistence, and extension rules |
| [API](api.md) | Integrators | HTTP resource groups, jobs, SSE, and compatibility policy |
| [Deployment](deployment.md) | Operators | Deploy behind systemd and nginx |
| [Development](development.md) | Contributors | Repository workflow, code organization, and quality gates |
| [Testing](testing.md) | Contributors | Offline tests, parser corpus, and verification expectations |
| [Data and privacy](data-and-privacy.md) | Everyone | Local data, third-party PDFs, release hygiene, and deletion |
| [Product scope](product-scope.md) | Maintainers | Supported use cases and explicit non-goals |
| [Design decisions](design-decisions.md) | Maintainers | Important trade-offs and their consequences |
| [Roadmap](roadmap.md) | Everyone | Planned work, ordered by project pressure rather than dates |
| [OpenCode assessment](opencode-assessment.md) | Maintainers | Why PaperLens should borrow patterns but not migrate wholesale |

## Repository policies

- [Contributing](../CONTRIBUTING.md)
- [Security policy](../SECURITY.md)
- [Code of conduct](../CODE_OF_CONDUCT.md)
- [Changelog](../CHANGELOG.md)

Configuration templates for the reference single-host deployment remain in
[`nginx/`](nginx/) and [`systemd/`](systemd/). Treat them as examples: review
paths, users, origins, TLS, and credentials before production use.
