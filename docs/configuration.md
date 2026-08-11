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
| `PAPERLENS_PDF_PARSER` | `hybrid` | Legacy compatibility setting. Production uploads use Parser v2 capability planning. |
| `PAPERLENS_GROBID_URL` | empty | Optional GROBID service base URL, for example `http://127.0.0.1:8070`. |
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
| `PAPERLENS_CORS_ORIGINS` | local frontend origins | Comma-separated browser origins allowed to send credentialed requests. Wildcards are not accepted. |
| `PAPERLENS_SECURE_COOKIES` | `false` | Set `true` behind HTTPS so anonymous workspace cookies use the `Secure` attribute. |

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
PAPERLENS_GROBID_URL=
PAPERLENS_USER_QUOTA=300
PAPERLENS_MAX_SYNC_FIGURES=10
PAPERLENS_CORS_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
PAPERLENS_SECURE_COOKIES=false
```

Never place real credentials in `.env.example`, issue reports, screenshots, or
committed deployment units.

## Optional parsing providers

The default install stays lightweight. Install Docling when structure recovery
quality justifies its model/runtime cost:

```bash
.venv/bin/pip install -e "core[docling]"
```

Install PaddleOCR-VL only on a machine prepared for its inference runtime. It
is reserved for pages flagged by the primary quality pass:

```bash
.venv/bin/pip install -e "core[paddleocr-vl]"
```

GROBID runs as a separate service and needs no additional PaperLens Python
dependency. Provider absence or failure is recorded and falls back to local
parsers; it does not prevent the application from starting.
