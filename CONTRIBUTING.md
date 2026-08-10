# Contributing to PaperLens

Thank you for helping improve PaperLens. Bug fixes, parser regression cases,
tests, documentation, accessibility work, and focused performance improvements
are especially welcome.

For large product features, storage changes, new parser backends, or new model
workflows, open an issue before implementation. Early discussion helps preserve
evidence semantics and avoids building an interface the project cannot support.

## Before you start

- Search existing issues and pull requests.
- Do not attach copyrighted or confidential PDFs to public issues.
- Never include API keys, `.env`, `.paperlens/`, databases, logs, or user data.
- Use a minimal synthetic fixture or an arXiv identifier when reporting a parser
  problem.

## Development setup

```bash
git clone https://github.com/ZilaiWang/paperlens.git
cd paperlens
python3 -m venv .venv
.venv/bin/pip install -e "core[server,dev]"

cd web
bun install --frozen-lockfile
```

See [Development](docs/development.md) for module ownership and compatibility
rules, and [Architecture](docs/architecture.md) before changing persisted or
evidence-related behavior.

## Making a change

1. Create a focused branch.
2. Keep domain logic in `core`, HTTP transport in `server`, and presentation in
   `web`.
3. Add a regression test for a bug fix or new behavior.
4. Update the owning documentation and `CHANGELOG.md` when user-visible behavior
   changes.
5. Run all relevant checks.

```bash
.venv/bin/ruff check core server scripts tests
.venv/bin/python -m pytest
cd web && bun run build
```

If parsing behavior changes, also download and run the manifest-based corpus as
described in [Testing](docs/testing.md).

## Pull requests

A good pull request:

- explains the user-visible problem and why the chosen boundary is correct;
- stays focused on one coherent change;
- lists validation performed;
- calls out persistence, API, privacy, performance, or provider implications;
- includes screenshots for UI changes, with private document content removed;
- does not mix broad formatting changes with behavior changes unless the
  formatting is the purpose of the pull request.

Draft pull requests are welcome for early feedback. Maintainers may ask to split
a change when review or rollback would otherwise be difficult.

## Commit style

Use concise conventional-style messages when practical:

```text
fix(comparison): restore request body contract
docs: rewrite deployment guide
test(parser): cover two-column heading regression
```

## Evidence and parser changes

These areas require extra care:

- preserve paper-version ownership for blocks, chunks, and evidence IDs;
- distinguish missing retrieval from confirmed absence;
- do not accept a generated numeric claim without source support;
- record parser provenance and quality gaps;
- keep offline paths independent of network and model configuration;
- do not silently change persisted identity semantics.

## Reporting security problems

Do not open a public issue for a vulnerability. Follow [SECURITY.md](SECURITY.md).

By participating, you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
