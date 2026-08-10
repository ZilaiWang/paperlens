"""Validated arXiv metadata lookup and PDF download.

Only whitelisted id formats are accepted; download validates MIME, PDF magic,
size and computes SHA-256. No arbitrary URLs (SSRF guard).
"""

from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
ARXIV_API = "https://export.arxiv.org/api/query"
MAX_PDF_MB = 80
MIN_INTERVAL_S = 3.0  # arXiv API etiquette: single connection, ≥3s between requests

_last_request: float = 0.0


def normalize_arxiv_input(value: str) -> str:
    """Accept https://arxiv.org/abs/X, /pdf/X, arXiv:X, or bare X."""
    stripped = value.strip()
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([^?#]+)", stripped)
    if match:
        candidate = match.group(1)
    elif stripped.lower().startswith("arxiv:"):
        candidate = stripped[6:]
    else:
        candidate = stripped
    candidate = candidate.split("v")[0] if re.match(r"^\d{4}\.\d{4,5}v\d+$", candidate) else candidate
    if not ARXIV_ID_RE.match(candidate):
        raise ValueError(f"不支持的 arXiv 标识符: {value!r}")
    return candidate


@dataclass
class ArxivMeta:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    pdf_url: str
    version: str = ""


def _throttle() -> None:
    global _last_request
    elapsed = time.monotonic() - _last_request
    if elapsed < MIN_INTERVAL_S:
        time.sleep(MIN_INTERVAL_S - elapsed)
    _last_request = time.monotonic()


def fetch_metadata(arxiv_id: str, *, contact_email: str = "") -> ArxivMeta:
    _throttle()
    from paperlens_core.net import make_arxiv_httpx_client

    headers = {"User-Agent": f"PaperLens/2.0 (mailto:{contact_email or 'paperlens@example.invalid'})"}
    with make_arxiv_httpx_client(timeout=30, headers=headers) as client:
        response = client.get(
                ARXIV_API, params={"id_list": arxiv_id, "max_results": 1}, follow_redirects=True
            )
        response.raise_for_status()
    root = ET.fromstring(response.text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise ValueError(f"arXiv 未找到该记录: {arxiv_id}")
    title = " ".join((entry.findtext("atom:title", default="", namespaces=ns) or "").split())
    authors = [a.findtext("atom:name", default="", namespaces=ns) for a in entry.findall("atom:author", ns)]
    summary = " ".join((entry.findtext("atom:summary", default="", namespaces=ns) or "").split())
    pdf_link = next(
        (link.attrib.get("href", "") for link in entry.findall("atom:link", ns) if link.attrib.get("title") == "pdf"),
        f"https://arxiv.org/pdf/{arxiv_id}",
    )
    return ArxivMeta(arxiv_id=arxiv_id, title=title, authors=authors, abstract=summary, pdf_url=pdf_link)


def download_pdf(arxiv_id: str, target_dir: str, *, contact_email: str = "") -> str:
    meta = fetch_metadata(arxiv_id, contact_email=contact_email)
    _throttle()
    from paperlens_core.net import make_arxiv_httpx_client

    headers = {"User-Agent": f"PaperLens/2.0 (mailto:{contact_email or 'paperlens@example.invalid'})"}
    with make_arxiv_httpx_client(
        timeout=120, follow_redirects=True, headers=headers
    ) as client:
        response = client.get(meta.pdf_url)
        response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF-"):
        raise ValueError("arXiv 返回的不是 PDF 文件")
    if len(raw) > MAX_PDF_MB * 1024 * 1024:
        raise ValueError(f"PDF 超过 {MAX_PDF_MB}MB 限制")
    import os

    os.makedirs(target_dir, exist_ok=True)
    sha = hashlib.sha256(raw).hexdigest()
    path = os.path.join(target_dir, f"arxiv-{arxiv_id.replace('/', '-')}-{sha[:12]}.pdf")
    with open(path, "wb") as handle:
        handle.write(raw)
    return path
