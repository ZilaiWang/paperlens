"""Structured operational logging (V3.6 日志系统).

All PaperLens logs go to ``data/logs/paperlens.log`` with rotation AND to
the console (so systemd journald keeps them too). Key events carry the
job_id and stage so any run — test or public beta — is traceable end to
end: what ran, how long each stage took, and where it failed.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_logger: logging.Logger | None = None


def setup_logging(data_dir: str) -> logging.Logger:
    """Configure the paperlens logger once; idempotent across reloads."""
    global _logger
    if _logger is not None:
        return _logger
    logger = logging.getLogger("paperlens")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    log_dir = os.path.join(data_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "paperlens.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    _logger = logger
    logger.info("paperlens logging ready -> %s", os.path.join(log_dir, "paperlens.log"))
    return logger


def get_logger() -> logging.Logger:
    """Logger accessor; safe before setup_logging (console-only then)."""
    return logging.getLogger("paperlens")
