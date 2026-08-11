"""Shared backend base: implements the ParserBackend protocol shell."""

from __future__ import annotations

from ..contracts import BackendProbe, BackendResult, ParseRequest


class BaseBackend:
    """Common adapter logic; subclasses implement ``_parse``."""

    name = "base"

    def __init__(self) -> None:
        self._document_path: str = ""
        self._raw_bytes: bytes | None = None

    def probe(self, document_path: str, raw_bytes: bytes | None = None) -> BackendProbe:
        try:
            available = getattr(self, "available", None)
            if callable(available) and not available():
                return BackendProbe(
                    backend=self.name,
                    available=False,
                    capabilities=set(),
                    note="optional backend is not configured",
                )
            caps = self.capabilities()
            return BackendProbe(backend=self.name, available=True, capabilities=caps)
        except Exception:  # noqa: BLE001 - probe never raises
            return BackendProbe(backend=self.name, available=False, capabilities=set())

    def parse(self, request: ParseRequest) -> BackendResult:
        self._document_path = request.document_path
        self._raw_bytes = request.raw_bytes
        try:
            candidates = self._parse(
                request.raw_bytes or b"",
                request.document_path,
                page_range=request.page_range,
            )
            return BackendResult(
                backend=self.name,
                backend_version="1.0",
                region=request.region,
                candidates=candidates,
            )
        except Exception as exc:  # noqa: BLE001 - record failure, never crash pipeline
            return BackendResult(
                backend=self.name,
                backend_version="1.0",
                region=request.region,
                candidates=[],
                error=f"{type(exc).__name__}: {exc}",
            )

    def _parse(self, raw_bytes: bytes, document_path: str, page_range=None):
        raise NotImplementedError
