"""Parser v2 backends: adapters around the existing V1 parsers.

Each backend wraps a concrete parser and emits ``ParseCandidate`` (never
DocumentIR), per the protocol in :mod:`parsing.contracts`.
"""

from .docling_backend import DoclingBackend
from .grobid_backend import GROBIDBackend
from .paddleocr_vl_backend import PaddleOCRVLBackend
from .pdfplumber_backend import PDFPlumberBackend
from .pymupdf_backend import PyMuPDFBackend

__all__ = [
    "DoclingBackend",
    "GROBIDBackend",
    "PaddleOCRVLBackend",
    "PyMuPDFBackend",
    "PDFPlumberBackend",
]
