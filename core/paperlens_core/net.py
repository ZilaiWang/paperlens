"""Outbound network policy (V3.6): arXiv-only proxy acceleration.

    export PAPERLENS_ARXIV_PROXY=http://127.0.0.1:7890

→ only arXiv endpoints (HTML pages, the export API, PDF downloads) go
through the proxy; every other provider (Crossref, doi.org, DeepSeek API)
stays on the direct path. This keeps academic lookups compliant and fast
while unblocking the slow arxiv.org HTML pages from the CN cloud server.
"""

from __future__ import annotations

import os


def arxiv_proxy_url() -> str:
    return os.environ.get("PAPERLENS_ARXIV_PROXY", "").strip()


def arxiv_proxies() -> dict[str, str] | None:
    """Legacy httpx ``proxies`` mapping (kept for tests); see arxiv_mounts."""
    url = arxiv_proxy_url()
    if not url:
        return None
    return {"http://": url, "https://": url}


def arxiv_mounts() -> dict[str, object] | None:
    """httpx 0.28+ ``mounts`` mapping for the arXiv proxy, else None.

    httpx 0.28 removed the ``proxies=`` constructor argument in favor of
    ``mounts={scheme: HTTPTransport(proxy=...)}``; this keeps every arXiv
    caller on the same proxy policy regardless of httpx version.
    """
    url = arxiv_proxy_url()
    if not url:
        return None
    import httpx

    transport = httpx.HTTPTransport(proxy=url)
    return {"http://": transport, "https://": transport}


def make_arxiv_httpx_client(*, timeout: float, **kwargs: object) -> object:
    """httpx.Client for arXiv endpoints with the proxy mounted (V3.7)."""
    import httpx

    mounts = arxiv_mounts()
    if not mounts:
        return httpx.Client(timeout=timeout, **kwargs)
    return httpx.Client(timeout=timeout, mounts=mounts, **kwargs)
