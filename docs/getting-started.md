# Getting started

This guide runs PaperLens locally with a Python API and a Bun/Next.js web app.
Parsing works without an LLM. Translation, question answering, analysis, and
comparison require an OpenAI-compatible model endpoint.

## 1. Install prerequisites

- Python 3.10+
- Bun 1.3+
- Git

The default install uses pdfplumber and requires no system PDF service. PyMuPDF
is an optional enhanced geometry/table backend because it has separate
AGPL/commercial licensing terms.

## 2. Install the backend

```bash
git clone https://github.com/ZilaiWang/paperlens.git
cd paperlens
python3 -m venv .venv
.venv/bin/pip install -e "core[server,dev]"
cp .env.example .env
```

To enable the PyMuPDF path used by `hybrid` when available:

```bash
.venv/bin/pip install -e "core[pymupdf]"
```

Review [Third-party notices](../THIRD_PARTY_NOTICES.md) before distributing or
hosting a build that includes it. Without PyMuPDF, `hybrid` falls back to
pdfplumber.

For local-model use, keep the default base URL and start an OpenAI-compatible
server on port `1234`. For a hosted provider, edit these values in `.env`:

```dotenv
OPENAI_BASE_URL=https://your-provider.example/v1
OPENAI_API_KEY=replace-me
PAPERLENS_MODEL=your-model-name
```

Do not commit `.env`.

## 3. Start the API

```bash
.venv/bin/uvicorn server.app.main:app --reload --host 127.0.0.1 --port 8700
```

Verify it in another terminal:

```bash
curl http://127.0.0.1:8700/api/health
```

Interactive OpenAPI documentation is available at
`http://127.0.0.1:8700/docs`.

## 4. Start the web app

```bash
cd web
bun install --frozen-lockfile
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8700 bun run dev
```

Open `http://127.0.0.1:3000`.

## 5. Import a paper

Use either of the two home-page inputs:

1. Upload a PDF that you are allowed to process.
2. Paste an arXiv identifier or URL, such as `1706.03762`.

Import returns a background job. The UI follows real stage progress while the
server parses pages, reconstructs sections, extracts references and assets,
builds chunks, and persists the document representation.

## What is stored locally?

The default data directory is `.paperlens/` and contains SQLite state, uploads,
downloaded PDFs, extracted assets, and logs. It is ignored by Git. See
[Data and privacy](data-and-privacy.md) before using sensitive documents.

## Common problems

### Model requests fail

Check `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `PAPERLENS_MODEL`. A successful
parse does not prove that model-backed features are configured.

### arXiv requests are slow or time out

Set `PAPERLENS_ARXIV_PROXY` when direct arXiv access is unreliable. The value is
an HTTP proxy URL, for example `http://127.0.0.1:7890`.

### The frontend cannot reach the API

Confirm `NEXT_PUBLIC_API_BASE` was set before starting or building Next.js, and
that `curl http://127.0.0.1:8700/api/health` succeeds.

### A scanned PDF has little or no text

PaperLens does not currently perform OCR. Scanned documents may be marked as a
parse gap. OCR is tracked as future work rather than silently generating text.
