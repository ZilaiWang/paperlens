# Configuration

PaperLens reads backend settings from environment variables and a repository-
root `.env` file. Copy `.env.example` as a starting point. Frontend public
variables are read by Next.js and must be present when the frontend starts or
builds.

## Model settings

| Variable | Default | Description |
| --- | --- | --- |
| `OPENAI_API_KEY` | empty | API credential. Local compatible servers may accept a placeholder. |
| `OPENAI_BASE_URL` | `http://127.0.0.1:1234/v1` | OpenAI-compatible base URL. |
| `PAPERLENS_MODEL` | `qwen2.5-7b-instruct` | Provider model identifier. |
| `PAPERLENS_TEMPERATURE` | `0.1` | Default model temperature, from 0 to 1. |
| `PAPERLENS_MAX_OUTPUT_TOKENS` | `1800` | Default structured-output budget. |
| `PAPERLENS_DISABLE_THINKING` | `false` | Requests non-thinking mode when the provider supports it. |

PaperLens expects reliable JSON output. A small or heavily quantized local model
may parse documents correctly but fail structured analysis schemas.

## Parsing and retrieval

| Variable | Default | Description |
| --- | --- | --- |
| `PAPERLENS_PDF_PARSER` | `hybrid` | `hybrid`, `pymupdf`, or `pdfplumber`. Hybrid prefers PyMuPDF and falls back by quality. |
| `PAPERLENS_MAX_PDF_MB` | `80` | Maximum accepted upload size in MiB. |
| `PAPERLENS_TOP_K` | `8` | Default number of BM25 retrieval hits. |
| `PAPERLENS_MAX_SYNC_FIGURES` | `10` | Number of remote figures downloaded during import before switching to on-demand fetch. |

## Storage and operation

| Variable | Default | Description |
| --- | --- | --- |
| `PAPERLENS_DATA_DIR` | `.paperlens` | SQLite database, uploads, extracted assets, and logs. |
| `PAPERLENS_USER_QUOTA` | `300` | Maximum papers associated with one `X-User-Id`. This is a quota, not authentication. |
| `CONTACT_EMAIL` | empty | Contact identity sent to scholarly services where supported. |
| `PAPERLENS_ARXIV_PROXY` | empty | Optional HTTP proxy for arXiv HTML, PDF, API, and asset requests. |

The current server is single-process. Running multiple Uvicorn workers against
the same SQLite database and in-memory job/event state is unsupported.

## Frontend

| Variable | Default | Description |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE` | `http://127.0.0.1:8700` in local examples | Browser-visible API origin. It is embedded into the frontend build. |

## Example: hosted OpenAI-compatible provider

```dotenv
OPENAI_API_KEY=replace-me
OPENAI_BASE_URL=https://api.example.com/v1
PAPERLENS_MODEL=example-chat-model
PAPERLENS_TEMPERATURE=0.1
PAPERLENS_MAX_OUTPUT_TOKENS=2000
PAPERLENS_DISABLE_THINKING=false

CONTACT_EMAIL=maintainer@example.com
PAPERLENS_DATA_DIR=.paperlens
PAPERLENS_MAX_PDF_MB=80
PAPERLENS_TOP_K=8
PAPERLENS_PDF_PARSER=hybrid
PAPERLENS_USER_QUOTA=300
PAPERLENS_MAX_SYNC_FIGURES=10
```

Never place real credentials in `.env.example`, issue reports, screenshots, or
committed deployment units.
