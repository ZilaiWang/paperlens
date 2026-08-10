# Deployment

This guide describes the supported reference deployment: one Linux host, one
Uvicorn process, one Next.js process, SQLite/local files, and nginx. It is suited
to personal or small trusted-team use.

PaperLens has no built-in authentication. Add an authentication layer and TLS
before exposing it beyond a trusted network.

## Topology

```text
browser -> nginx :443
             |-- /api/*         -> Uvicorn :8700
             `-- everything else -> Next.js :3000

Uvicorn -> local data directory + model/arXiv/metadata providers
```

Do not run multiple Uvicorn workers: live jobs and SSE events are currently
process-local.

## 1. Prepare the host

Install Python 3.10+, Bun or Node.js for the frontend, nginx, and a dedicated
unprivileged service account. The checked-in service examples use `ubuntu` and
`/home/ubuntu/paperlens`; change both for your host.

```bash
git clone https://github.com/ZilaiWang/paperlens.git /opt/paperlens
cd /opt/paperlens
python3 -m venv .venv
.venv/bin/pip install -e "core[server]"
cp .env.example .env
```

Install `core[pymupdf]` only after reviewing its AGPL/commercial terms in
[Third-party notices](../THIRD_PARTY_NOTICES.md). If it is not installed, hybrid
parsing falls back to pdfplumber.

Set a persistent absolute data directory in `.env`:

```dotenv
PAPERLENS_DATA_DIR=/var/lib/paperlens
```

Create it with ownership limited to the service account. Protect `.env` with
filesystem permissions such as `0600`.

## 2. Build the frontend

```bash
cd /opt/paperlens/web
bun install --frozen-lockfile
NEXT_PUBLIC_API_BASE=https://paperlens.example.com bun run build
```

`NEXT_PUBLIC_API_BASE` is a build-time browser value. Rebuild when the public
origin changes.

## 3. Configure services

Examples live in [`systemd/`](systemd/). Review and change:

- `User`, `Group`, and `WorkingDirectory`;
- `EnvironmentFile` and executable paths;
- the frontend runtime path;
- filesystem write permissions;
- process hardening appropriate for your environment.

After copying reviewed units:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pl-server pl-web
sudo systemctl status pl-server pl-web
```

## 4. Configure nginx and TLS

[`nginx/paperlens.conf`](nginx/paperlens.conf) demonstrates API proxying, SSE-
compatible buffering behavior, upload size, and differentiated caching. Replace
the catch-all server name, add TLS, and review timeouts.

Important rules:

- do not cache API responses except explicitly safe immutable/download content;
- disable proxy buffering for SSE;
- cache hashed `/_next/static/` assets for a long duration;
- avoid long-lived caching for HTML;
- restrict accepted origins and add authentication before public access.

Validate and reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Use an ACME client or managed load balancer for certificates. Plain HTTP is not
an acceptable public production configuration because model credentials,
document content, and session data may transit the service.

## 5. Verify

```bash
curl --fail http://127.0.0.1:8700/api/health
curl --fail https://paperlens.example.com/api/health
sudo journalctl -u pl-server -n 100 --no-pager
sudo journalctl -u pl-web -n 100 --no-pager
```

Then import one PDF and one arXiv paper and verify job progress, reading, model-
backed Q&A, translation, and asset downloads.

## Upgrades

1. Back up the data directory and `.env`.
2. Fetch a reviewed release tag.
3. Reinstall backend dependencies.
4. Reinstall/build the frontend from the lockfile.
5. Restart both services.
6. Verify health and a representative workflow.

The current repository performs lightweight SQLite migrations during startup.
Always keep a recoverable backup before upgrading.

## Backups

Back up the entire configured data directory, not only `paperlens.db`; WAL files
and uploaded/downloaded assets are part of the application state. Prefer a
SQLite-aware snapshot or stop the API briefly for a consistent file backup.

## Operational limits

- one API process;
- no built-in authentication or tenant isolation;
- no durable queue across process restarts;
- local disk determines document capacity and availability;
- external model and scholarly services determine model-backed feature latency.

If these limits are reached, follow the staged path in [Roadmap](roadmap.md)
instead of adding multiple workers to the current process-local architecture.
