## What changed?

Describe the problem and the user-visible outcome.

## Why this design?

Explain the chosen module boundary and important alternatives.

## Validation

- [ ] `ruff check core server scripts tests`
- [ ] `python -m pytest`
- [ ] `cd web && bun run build` (when frontend or API contracts change)
- [ ] Parser corpus or manual workflow checks (when relevant)

## Risk and compatibility

- [ ] No public API or persisted-schema break, or migration is documented
- [ ] Evidence/version ownership remains correct
- [ ] No credentials, private documents, databases, logs, or generated data
- [ ] Documentation and changelog updated when behavior changed

Add screenshots for UI changes after removing private paper content.
