"""Atomic, idempotent PDF ingestion orchestration."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .chunking import chunk_blocks
from .database import Database, DatabaseError
from .models import IngestResult
from .parser import PDFValidationError, parse_pdf_bytes, validate_pdf
from .sections import detect_sections
from .utils import sha256_bytes


class IngestionError(RuntimeError):
    """Base class for failures in the ingest workflow."""


class StoredPDFConflictError(IngestionError):
    """Raised instead of overwriting a stored path with unexpected bytes."""


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    result: IngestResult
    stored_path: Path
    deduplicated: bool


def _safe_file_name(file_name: str) -> str:
    # Treat backslashes as separators as well, even when running on POSIX.
    name = Path(file_name.replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        name = "paper.pdf"
    return name


def _hash_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_exclusive(path: Path, data: bytes, expected_hash: str) -> bool:
    """Publish fully written bytes without replacing an existing destination.

    Returns ``True`` when this call created the destination and ``False`` when
    an identical file was already present.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or _hash_file(path) != expected_hash:
            raise StoredPDFConflictError(f"存储路径已被不同内容占用：{path}")
        return False

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".paperlens-ingest-", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # A hard link is an atomic create-if-absent operation on the same filesystem.
            os.link(temporary_path, path)
            created = True
        except FileExistsError:
            if not path.is_file() or _hash_file(path) != expected_hash:
                raise StoredPDFConflictError(f"存储路径已被不同内容占用：{path}") from None
            created = False
        return created
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class IngestionService:
    """Validate, parse, enrich, store and persist one PDF as a single unit."""

    def __init__(
        self,
        database: Database,
        uploads_dir: str | Path,
        *,
        max_pdf_mb: int = 80,
        target_tokens: int = 420,
        max_tokens: int = 650,
    ) -> None:
        self.database = database
        self.uploads_dir = Path(uploads_dir).expanduser().resolve()
        self.max_pdf_mb = max_pdf_mb
        self.target_tokens = target_tokens
        self.max_tokens = max_tokens
        if target_tokens <= 0 or max_tokens < target_tokens:
            raise ValueError("chunk limits must satisfy 0 < target_tokens <= max_tokens")

    def _existing_outcome(self, file_sha256: str, data: bytes) -> IngestionOutcome | None:
        paper = self.database.get_paper_by_sha256(file_sha256)
        if paper is None:
            return None
        result = self.database.load_ingest_result(paper.paper_id)
        stored_path = self.database.get_stored_path(paper.paper_id)
        if result is None or stored_path is None:
            raise DatabaseError(f"论文 {paper.paper_id} 的持久记录不完整。")
        if stored_path.exists():
            if not stored_path.is_file() or _hash_file(stored_path) != file_sha256:
                raise StoredPDFConflictError(
                    f"论文 {paper.paper_id} 的已存 PDF 与数据库 SHA-256 不一致。"
                )
        else:
            # Recover a missing artifact only from bytes whose full hash is already verified.
            _write_exclusive(stored_path, data, file_sha256)
        return IngestionOutcome(result=result, stored_path=stored_path, deduplicated=True)

    def ingest_bytes(self, data: bytes, file_name: str) -> IngestionOutcome:
        validate_pdf(data, max_mb=self.max_pdf_mb)
        file_sha256 = sha256_bytes(data)
        existing = self._existing_outcome(file_sha256, data)
        if existing is not None:
            return existing

        safe_name = _safe_file_name(file_name)
        parsed = parse_pdf_bytes(data, safe_name, max_mb=self.max_pdf_mb)
        sections, assigned_blocks = detect_sections(parsed.paper.paper_id, parsed.blocks)
        chunks, final_blocks = chunk_blocks(
            parsed.paper.paper_id,
            assigned_blocks,
            target_tokens=self.target_tokens,
            max_tokens=self.max_tokens,
        )
        result = IngestResult(
            paper=parsed.paper,
            blocks=final_blocks,
            sections=sections,
            chunks=chunks,
            cleaning_events=parsed.cleaning_events,
        )
        stored_path = self.uploads_dir / f"{file_sha256}.pdf"
        created_file = False
        try:
            # BEGIN IMMEDIATE serializes the final duplicate check and all derived inserts.
            with self.database.transaction() as connection:
                concurrent = self.database.get_paper_by_sha256(file_sha256, connection=connection)
                if concurrent is not None:
                    # Another importer committed while this process was parsing.
                    pass
                else:
                    created_file = _write_exclusive(stored_path, data, file_sha256)
                    self.database.insert_ingest_result(result, stored_path, connection=connection)
            if concurrent is not None:
                duplicate = self._existing_outcome(file_sha256, data)
                if duplicate is None:  # defensive: transaction state should make this impossible
                    raise DatabaseError("并发去重后未找到已提交的论文。")
                return duplicate
        except BaseException:
            if created_file:
                stored_path.unlink(missing_ok=True)
            raise
        return IngestionOutcome(result=result, stored_path=stored_path, deduplicated=False)

    def ingest_file(self, path: str | Path) -> IngestionOutcome:
        source = Path(path)
        if not source.is_file():
            raise PDFValidationError(f"找不到 PDF 文件：{source}")
        return self.ingest_bytes(source.read_bytes(), source.name)


def ingest_pdf_bytes(
    data: bytes,
    file_name: str,
    *,
    database: Database,
    uploads_dir: str | Path,
    max_pdf_mb: int = 80,
) -> IngestionOutcome:
    """Functional entry point used by simple UI and CLI callers."""

    return IngestionService(database, uploads_dir, max_pdf_mb=max_pdf_mb).ingest_bytes(
        data, file_name
    )


__all__ = [
    "IngestionError",
    "IngestionOutcome",
    "IngestionService",
    "StoredPDFConflictError",
    "ingest_pdf_bytes",
]
