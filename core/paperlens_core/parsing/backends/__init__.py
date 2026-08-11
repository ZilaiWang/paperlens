"""Parser v2 backends: adapters around the existing V1 parsers.

Each backend wraps a concrete parser and emits ``ParseCandidate`` (never
DocumentIR), per the protocol in :mod:`parsing.contracts`.
"""

from .pdfplumber_backend import PDFPlumberBackend
from .pymupdf_backend import PyMuPDFBackend

__all__ = ["PyMuPDFBackend", "PDFPlumberBackend"]
