"""Optional GROBID semantic overlay backend."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Callable

from .base import BaseBackend


class GROBIDBackend(BaseBackend):
    """Read title/sections/references from a configured GROBID service."""

    name = "grobid"

    def __init__(
        self,
        base_url: str = "",
        *,
        request_fn: Callable[..., object] | None = None,
        timeout: float = 90.0,
    ) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.request_fn = request_fn
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.base_url or self.request_fn)

    def capabilities(self) -> set:
        from ..contracts import Capability

        return {
            Capability.BIBLIOGRAPHY,
            Capability.ACADEMIC_STRUCTURE,
            Capability.SEMANTIC,
        }

    def _parse(self, raw_bytes: bytes, document_path: str, page_range=None):
        if self.request_fn is not None:
            response = self.request_fn(
                raw_bytes=raw_bytes,
                document_path=document_path,
                page_range=page_range,
            )
            xml_text = getattr(response, "text", response)
        else:
            import httpx

            data: dict[str, str] = {"includeRawCitations": "1"}
            if page_range:
                data.update({"start": str(page_range[0]), "end": str(page_range[1])})
            response = httpx.post(
                f"{self.base_url}/api/processFulltextDocument",
                files={"input": (document_path.rsplit("/", 1)[-1], raw_bytes, "application/pdf")},
                data=data,
                timeout=self.timeout,
            )
            response.raise_for_status()
            xml_text = response.text
        return _tei_candidates(str(xml_text))


def _tei_candidates(xml_text: str):
    from ..candidates import CandidateKind, ParseCandidate

    root = ET.fromstring(xml_text)
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    specs = [
        (".//tei:titleStmt/tei:title", CandidateKind.HEADING, 0.98),
        (".//tei:body//tei:head", CandidateKind.HEADING, 0.95),
        (".//tei:listBibl/tei:biblStruct", CandidateKind.REFERENCE, 0.94),
    ]
    candidates = []
    for query, kind, confidence in specs:
        for element in root.findall(query, ns):
            text = " ".join("".join(element.itertext()).split())
            if not text:
                continue
            candidates.append(
                ParseCandidate(
                    candidate_id=f"grobid-{len(candidates):05d}",
                    backend="grobid",
                    page=1,
                    kind=kind,
                    text=text,
                    confidence=confidence,
                    raw_payload={"source_engine": "grobid", "semantic_overlay": True},
                )
            )
    return candidates
