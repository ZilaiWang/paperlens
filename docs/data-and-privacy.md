# Data and privacy

PaperLens is local-first but not zero-egress. PDF parsing and BM25 retrieval run
locally. Model-backed features send selected text and prompts to the configured
OpenAI-compatible endpoint. Scholarly identity resolution contacts external
metadata services, and arXiv import downloads remote content.

## Local data

By default, `.paperlens/` contains:

| Path | Contents |
| --- | --- |
| `paperlens.db` plus WAL files | Papers, versions, document payloads, jobs, sessions, messages, annotations, and comparisons |
| `uploads/` | User-uploaded and downloaded PDFs plus extracted assets |
| `logs/` | Rotating application logs |

This directory is ignored by Git. Operators are responsible for filesystem
permissions, backups, retention, and secure deletion.

Deleting a paper through the current API removes repository records but should
not be treated as a certified data-erasure workflow. Verify associated files and
backups when legal or organizational deletion requirements apply.

## External data flows

| Action | Possible destination | Data involved |
| --- | --- | --- |
| Translation, Q&A, analysis, comparison | Configured model provider | Retrieved or selected paper text, prompts, and conversation context |
| arXiv import | arXiv and configured proxy | arXiv identifier and network metadata; returned HTML/PDF/assets |
| Reference resolution | Crossref, DataCite, arXiv, and supported scholarly services | Citation metadata such as title, author, DOI, and year |

Review the privacy and retention terms of every configured provider. Do not use
confidential papers with a third-party model endpoint unless you have authority
to transmit their content.

## Repository and release hygiene

The repository must not contain:

- `.env` or credentials;
- `.paperlens/`, databases, logs, uploads, or caches;
- downloaded evaluation PDFs;
- third-party papers without explicit redistribution permission;
- generated frontend dependencies or build output.

The evaluation corpus is reproducible from `tests/eval_corpus/manifest.json`.
PDF files in that directory are explicitly ignored.

Run the release guard before publishing an archive:

```bash
.venv/bin/python scripts/package_release.py --check
```

The guard checks excluded directories, PDFs, common credential patterns, logs,
and local environment files. It is a defense-in-depth check, not a substitute
for reviewing Git history and enabling GitHub secret scanning.

## Existing Git history

Removing a sensitive or large file in a new commit does not remove it from prior
commits. If a credential was ever committed, revoke it first. If third-party
documents must be purged, coordinate a `git filter-repo` history rewrite with
all maintainers and force-push only after announcing the migration. History
rewrites invalidate existing clones and open branches, so they are an explicit
maintainer operation rather than part of normal cleanup.
