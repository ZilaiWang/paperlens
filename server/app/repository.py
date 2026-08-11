"""SQLite repository for DocumentIR entities and server state.

JSON-document storage keeps the single-process schema explicit and simple.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path

from paperlens_core.documents import (
    Annotation,
    Paper,
    PaperVersion,
)
from paperlens_core.jobs import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'UPLOAD',
    user_id TEXT NOT NULL DEFAULT 'guest',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS paper_versions (
    version_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    version_label TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'UPLOAD',
    file_name TEXT NOT NULL DEFAULT '',
    file_sha256 TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT '',
    page_count INTEGER NOT NULL DEFAULT 0,
    parse_status TEXT NOT NULL DEFAULT 'READY',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS documents (
    paper_version_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (paper_version_id, kind)
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    paper_id TEXT NOT NULL DEFAULT '',
    paper_version_id TEXT NOT NULL DEFAULT '',
    owner_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'QUEUED',
    stages TEXT NOT NULL DEFAULT '{}',
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    result_uri TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    paper_version_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS annotations (
    annotation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    paper_version_id TEXT NOT NULL,
    block_id TEXT NOT NULL DEFAULT '',
    char_start INTEGER NOT NULL DEFAULT 0,
    char_end INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'HIGHLIGHT',
    text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
-- V4.5：多篇比较结果（独立于论文文档存储）
CREATE TABLE IF NOT EXISTS comparisons (
    comparison_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);
-- V4.6-2：用户库条目——论文全局去重，收藏/归属按用户
CREATE TABLE IF NOT EXISTS user_papers (
    user_id TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    added_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, paper_id)
);
"""


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Repository:
    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connections = threading.local()
        connection = self._conn
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(SCHEMA)

    @property
    def _conn(self) -> sqlite3.Connection:
        """Return one SQLite connection per worker thread.

        FastAPI executes synchronous routes concurrently in a thread pool.
        Sharing one connection across those threads can produce intermittent
        ``InterfaceError`` failures even with ``check_same_thread=False``.
        """
        connection = getattr(self._connections, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.path, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=30000")
            self._connections.connection = connection
        return connection
        # migration: older DBs lack the user_id column (V3.6 quota)
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(papers)")}
        if "user_id" not in columns:
            self._conn.execute(
                "ALTER TABLE papers ADD COLUMN user_id TEXT NOT NULL DEFAULT 'guest'"
            )
        # migration: sessions 缺 updated_at（V4.6-1 会话管理）
        session_columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(sessions)")
        }
        if "updated_at" not in session_columns:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
            )
        self._conn.commit()

    # ---- papers / versions ----
    def create_paper(self, paper: Paper) -> None:
        # explicit column list: migrated DBs have user_id appended after
        # created_at, positional VALUES would swap the two (fix 2026-08-04)
        self._conn.execute(
            "INSERT OR IGNORE INTO papers (paper_id, title, source, user_id, created_at) "
            "VALUES (?,?,?,?,?)",
            (
                paper.paper_id,
                paper.canonical_title,
                paper.primary_source.value,
                paper.user_id,
                paper.created_at,
            ),
        )
        self._conn.commit()

    def count_papers_by_user(self, user_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS count FROM papers WHERE user_id=?", (user_id,)
        ).fetchone()
        return int(row["count"]) if row else 0

    def get_paper(self, paper_id: str) -> Paper | None:
        row = self._conn.execute("SELECT * FROM papers WHERE paper_id=?", (paper_id,)).fetchone()
        return Paper(paper_id=row["paper_id"], canonical_title=row["title"], primary_source=row["source"]) if row else None

    def list_papers(self) -> list[dict[str, object]]:
        # V4.6-0：附带当前版本 id（比较页等需要 version_id 而非 paper_id）
        rows = self._conn.execute(
            "SELECT p.*, "
            "(SELECT COUNT(*) FROM paper_versions v WHERE v.paper_id=p.paper_id) AS versions, "
            "(SELECT v.version_id FROM paper_versions v WHERE v.paper_id=p.paper_id "
            " ORDER BY v.created_at DESC LIMIT 1) AS version_id "
            "FROM papers p ORDER BY p.created_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    # ---- comparisons（V4.5）----
    def save_comparison(self, comparison_id: str, payload: dict[str, object]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO comparisons (comparison_id, payload, created_at) VALUES (?,?,?)",
            (comparison_id, json.dumps(payload, ensure_ascii=False), now_iso()),
        )
        self._conn.commit()

    def load_comparison(self, comparison_id: str) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT payload FROM comparisons WHERE comparison_id=?", (comparison_id,)
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_comparisons(self, limit: int = 10) -> list[dict[str, object]]:
        """V4.7（审计 P2）：比较历史列表（状态/对齐/论文/时间）。"""
        rows = self._conn.execute(
            "SELECT payload, created_at FROM comparisons ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        items = []
        for row in rows:
            payload = json.loads(row["payload"])
            items.append(
                {
                    "comparison_id": payload.get("comparison_id"),
                    "status": payload.get("status", "?"),
                    "paper_version_ids": payload.get("paper_version_ids", []),
                    "alignment": payload.get("alignment", {}).get("alignment", ""),
                    "error": payload.get("error", ""),
                    "created_at": payload.get("created_at") or row["created_at"],
                }
            )
        return items

    # ---- user_papers（V4.6-2 §14.1）----
    def add_user_paper(self, user_id: str, paper_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO user_papers (user_id, paper_id, added_at) VALUES (?,?,?)",
            (user_id, paper_id, now_iso()),
        )
        self._conn.commit()

    def list_user_papers(self, user_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT paper_id FROM user_papers WHERE user_id=? ORDER BY added_at DESC",
            (user_id,),
        ).fetchall()
        return [row["paper_id"] for row in rows]

    def create_version(self, version: PaperVersion) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO paper_versions VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                version.version_id,
                version.paper_id,
                version.version_label,
                version.source.value,
                version.file_name,
                version.file_sha256,
                version.file_path,
                version.page_count,
                version.parse_status.value,
                version.created_at,
            ),
        )
        self._conn.commit()

    def update_version_file_path(self, version_id: str, file_path: str) -> None:
        """Attach a PDF to an HTML-parsed version so the 原版 viewer works."""
        self._conn.execute(
            "UPDATE paper_versions SET file_path=? WHERE version_id=?",
            (file_path, version_id),
        )
        self._conn.commit()

    def update_version_page_count(self, version_id: str, page_count: int) -> None:
        """Persist the authoritative count discovered by the parser probe."""
        self._conn.execute(
            "UPDATE paper_versions SET page_count=? WHERE version_id=?",
            (page_count, version_id),
        )
        self._conn.commit()

    def get_version(self, version_id: str) -> PaperVersion | None:
        row = self._conn.execute(
            "SELECT * FROM paper_versions WHERE version_id=?", (version_id,)
        ).fetchone()
        if not row:
            return None
        return PaperVersion(
            version_id=row["version_id"],
            paper_id=row["paper_id"],
            version_label=row["version_label"],
            source=row["source"],
            file_name=row["file_name"],
            file_sha256=row["file_sha256"],
            file_path=row["file_path"],
            page_count=row["page_count"],
            parse_status=row["parse_status"],
            created_at=row["created_at"],
        )

    def delete_paper(self, paper_id: str) -> None:
        versions = self._conn.execute(
            "SELECT version_id, file_path FROM paper_versions WHERE paper_id=?", (paper_id,)
        ).fetchall()
        for row in versions:
            self._conn.execute("DELETE FROM documents WHERE paper_version_id=?", (row["version_id"],))
            if row["file_path"]:
                Path(row["file_path"]).unlink(missing_ok=True)
        self._conn.execute("DELETE FROM paper_versions WHERE paper_id=?", (paper_id,))
        self._conn.execute("DELETE FROM papers WHERE paper_id=?", (paper_id,))
        self._conn.commit()

    # ---- documents ----
    def store_document(self, paper_version_id: str, kind: str, payload: list[dict[str, object]]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO documents (paper_version_id, kind, payload) VALUES (?,?,?)",
            (paper_version_id, kind, json.dumps(payload, ensure_ascii=False)),
        )
        self._conn.commit()

    def load_document(self, paper_version_id: str, kind: str) -> list[dict[str, object]]:
        row = self._conn.execute(
            "SELECT payload FROM documents WHERE paper_version_id=? AND kind=?", (paper_version_id, kind)
        ).fetchone()
        return json.loads(row["payload"]) if row else []

    # ---- jobs ----
    def create_job(self, job: Job) -> None:
        self._conn.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job.job_id,
                job.job_type.value,
                job.paper_id,
                job.paper_version_id,
                job.owner_id,
                job.status.value,
                json.dumps({k: v.model_dump(mode="json") for k, v in job.stages.items()}),
                job.error_code,
                job.error_message,
                job.result_uri,
                job.created_at,
                job.updated_at,
            ),
        )
        self._conn.commit()

    def update_job(self, job: Job) -> None:
        self._conn.execute(
            "UPDATE jobs SET paper_id=?, paper_version_id=?, status=?, stages=?, "
            "error_code=?, error_message=?, result_uri=?, updated_at=? WHERE job_id=?",
            (
                job.paper_id,
                job.paper_version_id,
                job.status.value,
                json.dumps({k: v.model_dump(mode="json") for k, v in job.stages.items()}),
                job.error_code,
                job.error_message,
                job.result_uri,
                job.updated_at,
                job.job_id,
            ),
        )
        self._conn.commit()

    def get_job(self, job_id: str) -> Job | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        stages = json.loads(row["stages"])
        job = Job(
            job_id=row["job_id"],
            job_type=row["job_type"],
            paper_id=row["paper_id"],
            paper_version_id=row["paper_version_id"],
            owner_id=row["owner_id"],
            status=row["status"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            result_uri=row["result_uri"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        from paperlens_core.jobs import JobStage

        job.stages = {key: JobStage.model_validate(value) for key, value in stages.items()}
        return job

    # ---- sessions / messages ----
    def create_session(self, session_id: str, user_id: str, paper_version_id: str, title: str = "") -> None:
        # 显式列名：sessions 表 V4.6-1 加了 updated_at 列，位置绑定会错位
        #（fix 2026-08-04：5 值对 6 列 → OperationalError，Agent 完全无法发消息）
        created = now_iso()
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, user_id, paper_version_id, title, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (session_id, user_id, paper_version_id, title, created, created),
        )
        self._conn.commit()

    # ---- sessions management（V4.6-1 §3.4）----
    def list_sessions(self, paper_version_id: str, user_id: str) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT session_id, title, created_at, updated_at FROM sessions "
            "WHERE paper_version_id=? AND user_id=? ORDER BY updated_at DESC",
            (paper_version_id, user_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def rename_session(self, session_id: str, title: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET title=?, updated_at=? WHERE session_id=?",
            (title, now_iso(), session_id),
        )
        self._conn.commit()

    def delete_session(self, session_id: str) -> None:
        self._conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        self._conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        self._conn.commit()

    def append_message(self, session_id: str, role: str, content: str, evidence: list[dict[str, object]]) -> str:
        message_id = f"msg-{uuid.uuid4().hex[:12]}"
        self._conn.execute(
            "INSERT INTO messages VALUES (?,?,?,?,?,?)",
            (message_id, session_id, role, content, json.dumps(evidence, ensure_ascii=False), now_iso()),
        )
        self._conn.commit()
        return message_id

    def list_messages(self, session_id: str) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY created_at", (session_id,)
        ).fetchall()
        return [dict(row) | {"evidence": json.loads(row["evidence"])} for row in rows]

    # ---- annotations ----
    def save_annotation(self, annotation: Annotation) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO annotations VALUES (?,?,?,?,?,?,?,?,?)",
            (
                annotation.annotation_id,
                annotation.user_id,
                annotation.paper_version_id,
                annotation.block_id,
                annotation.char_start,
                annotation.char_end,
                annotation.kind.value,
                annotation.text,
                annotation.created_at,
            ),
        )
        self._conn.commit()

    def list_annotations(self, user_id: str, paper_version_id: str) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT * FROM annotations WHERE user_id=? AND paper_version_id=?",
            (user_id, paper_version_id),
        ).fetchall()
        return [dict(row) for row in rows]
