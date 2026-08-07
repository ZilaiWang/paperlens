"""SQLite persistence for parsed papers and PaperLens runtime state.

The database deliberately uses short-lived connections.  Every connection is
configured with the same safety pragmas, and every multi-table write is wrapped
in an explicit transaction.  Paper imports are append-only: callers must never
silently replace an existing paper or any of its derived records.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import (
    Block,
    Chunk,
    CleaningEvent,
    IngestResult,
    Paper,
    QualityAssessment,
    Section,
    utc_now_iso,
)
from .utils import stable_json

SCHEMA_VERSION = 1


class DatabaseError(RuntimeError):
    """Base class for persistence failures that are meaningful to callers."""


class PaperAlreadyExistsError(DatabaseError):
    """Raised when an append-only import attempts to insert the same PDF."""


class PaperIdentityConflictError(DatabaseError):
    """Raised when a short paper id is already bound to another full hash."""


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    authors_json TEXT NOT NULL DEFAULT '[]',
    file_name TEXT NOT NULL,
    file_sha256 TEXT NOT NULL UNIQUE,
    stored_path TEXT NOT NULL,
    page_count INTEGER NOT NULL CHECK (page_count >= 0),
    language TEXT NOT NULL,
    parser_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    parse_status TEXT NOT NULL CHECK (parse_status IN ('READY', 'PARTIAL', 'FAILED')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sections (
    section_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    title TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    level INTEGER NOT NULL CHECK (level >= 1),
    start_page INTEGER NOT NULL CHECK (start_page >= 1),
    end_page INTEGER CHECK (end_page IS NULL OR end_page >= start_page),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    heading_block_id TEXT,
    FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE,
    FOREIGN KEY (heading_block_id) REFERENCES blocks(block_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS blocks (
    block_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    page INTEGER NOT NULL CHECK (page >= 1),
    block_index INTEGER NOT NULL CHECK (block_index >= 0),
    bbox_x0 REAL NOT NULL,
    bbox_top REAL NOT NULL,
    bbox_x1 REAL NOT NULL,
    bbox_bottom REAL NOT NULL,
    block_type TEXT NOT NULL CHECK (
        block_type IN ('TEXT', 'FIGURE', 'TABLE', 'FORMULA', 'UNKNOWN_MEDIA')
    ),
    text TEXT NOT NULL,
    font_size REAL,
    is_bold INTEGER NOT NULL CHECK (is_bold IN (0, 1)),
    content_sha256 TEXT NOT NULL,
    section_id TEXT,
    section_path TEXT NOT NULL,
    paragraph_index INTEGER,
    source_scope TEXT NOT NULL CHECK (
        source_scope IN ('FULL_TEXT', 'ABSTRACT_ONLY', 'METADATA_ONLY')
    ),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (paper_id, page, block_index),
    FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE,
    FOREIGN KEY (section_id) REFERENCES sections(section_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    section_id TEXT,
    section_path TEXT NOT NULL,
    page_start INTEGER NOT NULL CHECK (page_start >= 1),
    page_end INTEGER NOT NULL CHECK (page_end >= page_start),
    text TEXT NOT NULL,
    token_estimate INTEGER NOT NULL CHECK (token_estimate >= 0),
    content_sha256 TEXT NOT NULL,
    FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE,
    FOREIGN KEY (section_id) REFERENCES sections(section_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS chunk_blocks (
    chunk_id TEXT NOT NULL,
    block_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (chunk_id, ordinal),
    UNIQUE (chunk_id, block_id),
    FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    FOREIGN KEY (block_id) REFERENCES blocks(block_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cleaning_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    page INTEGER CHECK (page IS NULL OR page >= 1),
    detail TEXT NOT NULL,
    count INTEGER NOT NULL CHECK (count >= 1),
    created_at TEXT NOT NULL,
    FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    current_paper_id TEXT,
    state_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (current_paper_id) REFERENCES papers(paper_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS usage (
    usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    session_id TEXT,
    stage TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    input_tokens INTEGER,
    output_tokens INTEGER,
    token_source TEXT NOT NULL CHECK (token_source IN ('reported', 'estimated', 'unknown')),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    status TEXT NOT NULL,
    error_code TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS api_cache (
    cache_key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    status_code INTEGER,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quality_outputs (
    output_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    session_id TEXT,
    rubric_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL DEFAULT '',
    assessment_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS preferences (
    user_id TEXT NOT NULL,
    preference_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, preference_key)
);

CREATE TABLE IF NOT EXISTS consents (
    consent_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    consent_type TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    scope_hash TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    decided_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sections_paper_page
    ON sections(paper_id, start_page, level);
CREATE INDEX IF NOT EXISTS idx_blocks_paper_order
    ON blocks(paper_id, page, block_index);
CREATE INDEX IF NOT EXISTS idx_blocks_section ON blocks(section_id);
CREATE INDEX IF NOT EXISTS idx_chunks_paper_order
    ON chunks(paper_id, page_start, chunk_id);
CREATE INDEX IF NOT EXISTS idx_cleaning_paper ON cleaning_events(paper_id, event_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user_updated ON sessions(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_session_started ON usage(session_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_cache_expiry ON api_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_quality_paper_created
    ON quality_outputs(paper_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_consents_lookup
    ON consents(user_id, consent_type, endpoint, scope_hash, decided_at DESC);
"""


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise DatabaseError("数据库中的 JSON 字段已损坏。") from exc


class Database:
    """PaperLens SQLite repository with explicit transaction boundaries."""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5_000) -> None:
        if busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must not be negative")
        self.path = Path(path).expanduser().resolve()
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=max(0.001, self.busy_timeout_ms / 1_000),
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms:d}")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured read/autocommit connection and always close it."""

        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(SCHEMA_SQL)
            connection.execute(
                """
                INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        """Yield a connection whose changes commit or roll back as one unit."""

        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _paper_from_row(row: sqlite3.Row) -> Paper:
        return Paper(
            paper_id=row["paper_id"],
            title=row["title"],
            authors=_json_loads(row["authors_json"], []),
            file_name=row["file_name"],
            file_sha256=row["file_sha256"],
            page_count=row["page_count"],
            language=row["language"],
            parser_name=row["parser_name"],
            parser_version=row["parser_version"],
            parse_status=row["parse_status"],
            created_at=row["created_at"],
        )

    def _paper_row(
        self,
        *,
        paper_id: str | None = None,
        file_sha256: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> sqlite3.Row | None:
        if (paper_id is None) == (file_sha256 is None):
            raise ValueError("provide exactly one of paper_id or file_sha256")
        own_connection = connection is None
        connection = connection or self.connect()
        try:
            column, value = (
                ("paper_id", paper_id)
                if paper_id is not None
                else (
                    "file_sha256",
                    file_sha256,
                )
            )
            return connection.execute(
                f"SELECT * FROM papers WHERE {column} = ?",  # column is selected above
                (value,),
            ).fetchone()
        finally:
            if own_connection:
                connection.close()

    def get_paper(
        self, paper_id: str, *, connection: sqlite3.Connection | None = None
    ) -> Paper | None:
        row = self._paper_row(paper_id=paper_id, connection=connection)
        return self._paper_from_row(row) if row else None

    def get_paper_by_sha256(
        self, file_sha256: str, *, connection: sqlite3.Connection | None = None
    ) -> Paper | None:
        row = self._paper_row(file_sha256=file_sha256, connection=connection)
        return self._paper_from_row(row) if row else None

    def get_stored_path(
        self, paper_id: str, *, connection: sqlite3.Connection | None = None
    ) -> Path | None:
        row = self._paper_row(paper_id=paper_id, connection=connection)
        return Path(row["stored_path"]) if row else None

    def list_papers(self) -> list[Paper]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM papers ORDER BY created_at, paper_id"
            ).fetchall()
        return [self._paper_from_row(row) for row in rows]

    def insert_ingest_result(
        self,
        result: IngestResult,
        stored_path: str | Path,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        """Insert one complete parse without replacing any existing records."""

        if connection is None:
            with self.transaction() as transaction:
                self._insert_ingest_result(result, Path(stored_path), transaction)
            return
        self._insert_ingest_result(result, Path(stored_path), connection)

    def _insert_ingest_result(
        self, result: IngestResult, stored_path: Path, connection: sqlite3.Connection
    ) -> None:
        paper = result.paper
        same_hash = self._paper_row(file_sha256=paper.file_sha256, connection=connection)
        if same_hash:
            raise PaperAlreadyExistsError(
                f"PDF 已导入：{same_hash['paper_id']} ({paper.file_sha256})"
            )
        same_id = self._paper_row(paper_id=paper.paper_id, connection=connection)
        if same_id:
            raise PaperIdentityConflictError(
                f"paper_id {paper.paper_id} 已绑定到另一个 SHA-256；拒绝覆盖。"
            )

        connection.execute(
            """
            INSERT INTO papers(
                paper_id, title, authors_json, file_name, file_sha256, stored_path,
                page_count, language, parser_name, parser_version, parse_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper.paper_id,
                paper.title,
                stable_json(paper.authors),
                paper.file_name,
                paper.file_sha256,
                str(stored_path.expanduser().resolve()),
                paper.page_count,
                paper.language,
                paper.parser_name,
                paper.parser_version,
                paper.parse_status.value,
                paper.created_at,
            ),
        )

        connection.executemany(
            """
            INSERT INTO sections(
                section_id, paper_id, title, canonical_name, level, start_page,
                end_page, confidence, heading_block_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.section_id,
                    item.paper_id,
                    item.title,
                    item.canonical_name,
                    item.level,
                    item.start_page,
                    item.end_page,
                    item.confidence,
                    item.heading_block_id,
                )
                for item in result.sections
            ],
        )
        connection.executemany(
            """
            INSERT INTO blocks(
                block_id, paper_id, page, block_index, bbox_x0, bbox_top, bbox_x1,
                bbox_bottom, block_type, text, font_size, is_bold, content_sha256,
                section_id, section_path, paragraph_index, source_scope, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.block_id,
                    item.paper_id,
                    item.page,
                    item.block_index,
                    *item.bbox,
                    item.block_type.value,
                    item.text,
                    item.font_size,
                    int(item.is_bold),
                    item.content_sha256,
                    item.section_id,
                    item.section_path,
                    item.paragraph_index,
                    item.source_scope,
                    stable_json(item.metadata),
                )
                for item in result.blocks
            ],
        )
        connection.executemany(
            """
            INSERT INTO chunks(
                chunk_id, paper_id, section_id, section_path, page_start, page_end,
                text, token_estimate, content_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.chunk_id,
                    item.paper_id,
                    item.section_id,
                    item.section_path,
                    item.page_start,
                    item.page_end,
                    item.text,
                    item.token_estimate,
                    item.content_sha256,
                )
                for item in result.chunks
            ],
        )
        connection.executemany(
            "INSERT INTO chunk_blocks(chunk_id, block_id, ordinal) VALUES (?, ?, ?)",
            [
                (chunk.chunk_id, block_id, ordinal)
                for chunk in result.chunks
                for ordinal, block_id in enumerate(chunk.block_ids)
            ],
        )
        connection.executemany(
            """
            INSERT INTO cleaning_events(
                paper_id, event_type, page, detail, count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.paper_id,
                    item.event_type,
                    item.page,
                    item.detail,
                    item.count,
                    item.created_at,
                )
                for item in result.cleaning_events
            ],
        )

    def get_sections(self, paper_id: str) -> list[Section]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM sections WHERE paper_id = ? ORDER BY start_page, section_id",
                (paper_id,),
            ).fetchall()
        return [
            Section(
                section_id=row["section_id"],
                paper_id=row["paper_id"],
                title=row["title"],
                canonical_name=row["canonical_name"],
                level=row["level"],
                start_page=row["start_page"],
                end_page=row["end_page"],
                confidence=row["confidence"],
                heading_block_id=row["heading_block_id"],
            )
            for row in rows
        ]

    def get_blocks(self, paper_id: str) -> list[Block]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM blocks WHERE paper_id = ? ORDER BY page, block_index",
                (paper_id,),
            ).fetchall()
        return [
            Block(
                block_id=row["block_id"],
                paper_id=row["paper_id"],
                page=row["page"],
                block_index=row["block_index"],
                bbox=(row["bbox_x0"], row["bbox_top"], row["bbox_x1"], row["bbox_bottom"]),
                block_type=row["block_type"],
                text=row["text"],
                font_size=row["font_size"],
                is_bold=bool(row["is_bold"]),
                content_sha256=row["content_sha256"],
                section_id=row["section_id"],
                section_path=row["section_path"],
                paragraph_index=row["paragraph_index"],
                source_scope=row["source_scope"],
                metadata=_json_loads(row["metadata_json"], {}),
            )
            for row in rows
        ]

    def get_chunks(self, paper_id: str) -> list[Chunk]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM chunks WHERE paper_id = ? ORDER BY page_start, chunk_id",
                (paper_id,),
            ).fetchall()
            block_rows = connection.execute(
                """
                SELECT cb.chunk_id, cb.block_id
                FROM chunk_blocks cb
                JOIN chunks c ON c.chunk_id = cb.chunk_id
                WHERE c.paper_id = ?
                ORDER BY cb.chunk_id, cb.ordinal
                """,
                (paper_id,),
            ).fetchall()
        block_ids: dict[str, list[str]] = {}
        for row in block_rows:
            block_ids.setdefault(row["chunk_id"], []).append(row["block_id"])
        return [
            Chunk(
                chunk_id=row["chunk_id"],
                paper_id=row["paper_id"],
                section_id=row["section_id"],
                section_path=row["section_path"],
                page_start=row["page_start"],
                page_end=row["page_end"],
                block_ids=block_ids.get(row["chunk_id"], []),
                text=row["text"],
                token_estimate=row["token_estimate"],
                content_sha256=row["content_sha256"],
            )
            for row in rows
        ]

    def get_cleaning_events(self, paper_id: str) -> list[CleaningEvent]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM cleaning_events WHERE paper_id = ? ORDER BY event_id",
                (paper_id,),
            ).fetchall()
        return [
            CleaningEvent(
                paper_id=row["paper_id"],
                event_type=row["event_type"],
                page=row["page"],
                detail=row["detail"],
                count=row["count"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def load_ingest_result(self, paper_id: str) -> IngestResult | None:
        paper = self.get_paper(paper_id)
        if paper is None:
            return None
        return IngestResult(
            paper=paper,
            sections=self.get_sections(paper_id),
            blocks=self.get_blocks(paper_id),
            chunks=self.get_chunks(paper_id),
            cleaning_events=self.get_cleaning_events(paper_id),
        )

    def upsert_session(
        self,
        session_id: str,
        user_id: str,
        *,
        title: str = "",
        current_paper_id: str | None = None,
        state: Mapping[str, Any] | None = None,
    ) -> None:
        now = utc_now_iso()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sessions(
                    session_id, user_id, title, current_paper_id, state_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    title = excluded.title,
                    current_paper_id = excluded.current_paper_id,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    user_id,
                    title,
                    current_paper_id,
                    stable_json(dict(state or {})),
                    now,
                    now,
                ),
            )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["state"] = _json_loads(result.pop("state_json"), {})
        return result

    def record_usage(self, **values: Any) -> int:
        required = {"run_id", "stage", "model", "latency_ms", "status"}
        missing = required - values.keys()
        if missing:
            raise ValueError(f"missing usage fields: {', '.join(sorted(missing))}")
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO usage(
                    run_id, session_id, stage, model, prompt_version, started_at,
                    latency_ms, input_tokens, output_tokens, token_source,
                    retry_count, status, error_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["run_id"],
                    values.get("session_id"),
                    values["stage"],
                    values["model"],
                    values.get("prompt_version", ""),
                    values.get("started_at", utc_now_iso()),
                    values["latency_ms"],
                    values.get("input_tokens"),
                    values.get("output_tokens"),
                    values.get("token_source", "unknown"),
                    values.get("retry_count", 0),
                    values["status"],
                    values.get("error_code", ""),
                ),
            )
            return int(cursor.lastrowid)

    def list_usage(self, *, session_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM usage"
        params: tuple[Any, ...] = ()
        if session_id is not None:
            query += " WHERE session_id = ?"
            params = (session_id,)
        query += " ORDER BY usage_id"
        with self.connection() as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]

    def put_api_cache(
        self,
        cache_key: str,
        *,
        provider: str,
        request_hash: str,
        response: Any,
        expires_at: str,
        status_code: int | None = None,
    ) -> None:
        now = utc_now_iso()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO api_cache(
                    cache_key, provider, request_hash, response_json, status_code,
                    expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    provider = excluded.provider,
                    request_hash = excluded.request_hash,
                    response_json = excluded.response_json,
                    status_code = excluded.status_code,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    cache_key,
                    provider,
                    request_hash,
                    stable_json(response),
                    status_code,
                    expires_at,
                    now,
                    now,
                ),
            )

    def get_api_cache(self, cache_key: str, *, now: str | None = None) -> dict[str, Any] | None:
        now = now or utc_now_iso()
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM api_cache WHERE cache_key = ? AND expires_at > ?",
                (cache_key, now),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["response"] = _json_loads(result.pop("response_json"), None)
        return result

    def save_quality_output(
        self,
        output_id: str,
        paper_id: str,
        assessment: QualityAssessment | Mapping[str, Any],
        *,
        rubric_version: str,
        prompt_version: str = "",
        session_id: str | None = None,
    ) -> None:
        payload = (
            assessment.model_dump(mode="json")
            if isinstance(assessment, QualityAssessment)
            else dict(assessment)
        )
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO quality_outputs(
                    output_id, paper_id, session_id, rubric_version,
                    prompt_version, assessment_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    output_id,
                    paper_id,
                    session_id,
                    rubric_version,
                    prompt_version,
                    stable_json(payload),
                    utc_now_iso(),
                ),
            )

    def list_quality_outputs(self, paper_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM quality_outputs WHERE paper_id = ? ORDER BY created_at",
                (paper_id,),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row)
            value["assessment"] = _json_loads(value.pop("assessment_json"), {})
            results.append(value)
        return results

    def set_preference(self, user_id: str, key: str, value: Any) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO preferences(user_id, preference_key, value_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, preference_key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (user_id, key, stable_json(value), utc_now_iso()),
            )

    def get_preference(self, user_id: str, key: str, default: Any = None) -> Any:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT value_json FROM preferences
                WHERE user_id = ? AND preference_key = ?
                """,
                (user_id, key),
            ).fetchone()
        return _json_loads(row["value_json"], default) if row else default

    def record_consent(
        self,
        user_id: str,
        consent_type: str,
        endpoint: str,
        scope_hash: str,
        decision: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> int:
        decision = decision.upper()
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("decision must be APPROVED or REJECTED")
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO consents(
                    user_id, consent_type, endpoint, scope_hash, decision,
                    metadata_json, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    consent_type,
                    endpoint,
                    scope_hash,
                    decision,
                    stable_json(dict(metadata or {})),
                    utc_now_iso(),
                ),
            )
            return int(cursor.lastrowid)

    def latest_consent(
        self, user_id: str, consent_type: str, endpoint: str, scope_hash: str
    ) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM consents
                WHERE user_id = ? AND consent_type = ? AND endpoint = ? AND scope_hash = ?
                ORDER BY consent_id DESC LIMIT 1
                """,
                (user_id, consent_type, endpoint, scope_hash),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["metadata"] = _json_loads(result.pop("metadata_json"), {})
        return result


# Descriptive alias retained for callers that prefer an explicit class name.
PaperLensDatabase = Database


__all__ = [
    "Database",
    "DatabaseError",
    "PaperAlreadyExistsError",
    "PaperIdentityConflictError",
    "PaperLensDatabase",
    "SCHEMA_VERSION",
]
