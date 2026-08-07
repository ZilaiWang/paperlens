"""统一 PDF 解析入口（改进方案3 §3.1 / §6.5，V4.0-4）。

业务代码（jobs、eval）不得直接 import 具体 parser——一律经
``ParseRouter.parse_pdf`` 进入，解析后端由配置 ``PAPERLENS_PDF_PARSER``
决定：

- ``hybrid``（默认）：PyMuPDF 几何提取（span/方向/表格遮罩）优先，
  异常时自动回退 pdfplumber 旧管线（服务器缺 fitz 也能跑）；
- ``pymupdf``：强制 PyMuPDF；
- ``pdfplumber``：强制旧管线（回归对比用）。

GROBID / Docling / PP-Structure 属 V4.2 多源融合规划，接口保持在此类
路由上扩展。
"""

from __future__ import annotations

import logging
from typing import Any

from .config import Settings

logger = logging.getLogger("paperlens.core.parse_router")


class ParseRouter:
    """PDF 解析后端路由；输出形状与 legacy parser 一致（paper + blocks）。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    def parse_pdf(self, raw: bytes, pdf_path: str) -> tuple[Any, str]:
        """按配置引擎解析，返回 (parsed, engine)。hybrid 失败自动回退。"""
        engine = (self.settings.paperlens_pdf_parser or "hybrid").strip().lower()
        if engine in ("pymupdf", "hybrid"):
            try:
                parsed = self.parse_with_engine(raw, pdf_path, "pymupdf")
                return parsed, "pymupdf"
            except Exception as exc:  # noqa: BLE001 - engine fallback
                if engine == "pymupdf":
                    raise
                logger.warning("pymupdf parse failed (%s) -> fallback pdfplumber", exc)
        parsed = self.parse_with_engine(raw, pdf_path, "pdfplumber")
        return parsed, "pdfplumber"

    def parse_with_engine(self, raw: bytes, pdf_path: str, engine: str):
        """显式引擎解析（V4.2 Active Quality Gate 用；失败抛出）。"""
        if engine == "pymupdf":
            from .pymupdf_adapter import parse_pdf_bytes_pymupdf

            parsed = parse_pdf_bytes_pymupdf(raw, pdf_path)
        else:
            from .parser import parse_pdf_bytes

            parsed = parse_pdf_bytes(raw, pdf_path)
        logger.info("pdf parsed with engine=%s (%.1f KB)", engine, len(raw) / 1024)
        return parsed


_router: ParseRouter | None = None


def parse_pdf(raw: bytes, pdf_path: str) -> tuple[Any, str]:
    """进程级单例路由（Settings 由环境/.env 加载，进程内不变）。

    返回 (parsed, engine)——V4.2 质量门需要知道实际使用的引擎。
    """
    global _router
    if _router is None:
        _router = ParseRouter()
    return _router.parse_pdf(raw, pdf_path)
