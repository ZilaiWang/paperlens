"""Thread checkpoints, long-term preferences, runtime skill loading, and HITL."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .utils import stable_json


class SQLiteLongTermStore:
    """Minimal persistent Store semantics with namespace isolation."""

    def __init__(self, database_path: Path | str):
        self.database_path = str(database_path)
        self._setup()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _setup(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS long_term_store (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(namespace, key)
                )
                """
            )

    @staticmethod
    def _namespace(namespace: tuple[str, ...] | list[str] | str) -> str:
        parts = [namespace] if isinstance(namespace, str) else list(namespace)
        if not parts or any(not part or "\x00" in part for part in parts):
            raise ValueError("namespace parts must be non-empty")
        return stable_json(parts)

    def put(self, namespace: tuple[str, ...] | list[str] | str, key: str, value: Any) -> None:
        if not key or "\x00" in key:
            raise ValueError("key must be non-empty")
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO long_term_store(namespace, key, value_json)
                VALUES (?, ?, ?)
                ON CONFLICT(namespace, key) DO UPDATE SET
                    value_json=excluded.value_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (self._namespace(namespace), key, payload),
            )

    def get(self, namespace: tuple[str, ...] | list[str] | str, key: str) -> Any | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM long_term_store WHERE namespace=? AND key=?",
                (self._namespace(namespace), key),
            ).fetchone()
        return json.loads(row["value_json"]) if row else None

    def search(
        self,
        namespace: tuple[str, ...] | list[str] | str,
        prefix: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT key, value_json, updated_at FROM long_term_store
                WHERE namespace=? AND key LIKE ? ESCAPE '\\'
                ORDER BY updated_at DESC, key LIMIT ?
                """,
                (self._namespace(namespace), _escape_like(prefix) + "%", max(1, min(limit, 100))),
            ).fetchall()
        return [
            {
                "key": row["key"],
                "value": json.loads(row["value_json"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def delete(self, namespace: tuple[str, ...] | list[str] | str, key: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM long_term_store WHERE namespace=? AND key=?",
                (self._namespace(namespace), key),
            )
            return cursor.rowcount > 0


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def load_review_skill(project_root: Path | str) -> dict[str, str]:
    path = Path(project_root) / "skills" / "evidence-paper-review" / "SKILL.md"
    content = path.read_text(encoding="utf-8")
    if "name: evidence-paper-review" not in content or "version:" not in content:
        raise ValueError("evidence paper review skill has invalid front matter")
    version = next(
        line.split(":", 1)[1].strip()
        for line in content.splitlines()
        if line.startswith("version:")
    )
    return {
        "name": "evidence-paper-review",
        "version": version,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content": content,
    }


class ConsentState(TypedDict, total=False):
    status: Literal[
        "LOCAL_CHECKED",
        "CONSENT_PENDING",
        "APPROVED",
        "REJECTED",
        "VERIFYING",
        "DONE",
        "LOCAL_ONLY_DONE",
    ]
    provider: str
    endpoint: str
    field_categories: list[str]
    content_preview_hash: str
    payload: dict[str, Any]
    decision: Literal["approve", "reject"]
    result: dict[str, Any]


class ConsentWorkflow:
    """A real LangGraph interrupt/resume gate placed immediately before egress."""

    def __init__(
        self,
        checkpoint_path: Path | str,
        external_call: Callable[[dict[str, Any]], dict[str, Any]],
        audit_callback: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.connection = sqlite3.connect(str(checkpoint_path), check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.checkpointer = SqliteSaver(self.connection)
        self.external_call = external_call
        self.audit_callback = audit_callback
        graph = StateGraph(ConsentState)
        graph.add_node("local_checked", self._local_checked)
        graph.add_node("consent", self._consent)
        graph.add_node("route_decision", self._route_decision)
        graph.add_node("verify", self._verify)
        graph.add_node("local_only", self._local_only)
        graph.add_edge(START, "local_checked")
        graph.add_edge("local_checked", "consent")
        graph.add_edge("consent", "route_decision")
        graph.add_conditional_edges(
            "route_decision",
            lambda state: "verify" if state["decision"] == "approve" else "local_only",
            {"verify": "verify", "local_only": "local_only"},
        )
        graph.add_edge("verify", END)
        graph.add_edge("local_only", END)
        self.graph = graph.compile(checkpointer=self.checkpointer)

    @staticmethod
    def _local_checked(state: ConsentState) -> ConsentState:
        return {"status": "LOCAL_CHECKED"}

    @staticmethod
    def _consent(state: ConsentState) -> ConsentState:
        decision = interrupt(
            {
                "status": "CONSENT_PENDING",
                "provider": state["provider"],
                "endpoint": state["endpoint"],
                "field_categories": state.get("field_categories", []),
                "content_preview_hash": state["content_preview_hash"],
            }
        )
        if decision not in {"approve", "reject"}:
            raise ValueError("resume value must be approve or reject")
        return {"decision": decision, "status": "APPROVED" if decision == "approve" else "REJECTED"}

    def _route_decision(self, state: ConsentState) -> ConsentState:
        if self.audit_callback:
            self.audit_callback(
                {
                    "provider": state["provider"],
                    "endpoint": state["endpoint"],
                    "scope_hash": state["content_preview_hash"],
                    "decision": state["decision"],
                }
            )
        return state

    def _verify(self, state: ConsentState) -> ConsentState:
        result = self.external_call(state.get("payload", {}))
        return {"status": "DONE", "result": result}

    @staticmethod
    def _local_only(state: ConsentState) -> ConsentState:
        return {"status": "LOCAL_ONLY_DONE", "result": {"network_called": False}}

    @staticmethod
    def initial_input(
        *, provider: str, endpoint: str, field_categories: list[str], payload: dict[str, Any]
    ) -> ConsentState:
        return {
            "status": "LOCAL_CHECKED",
            "provider": provider,
            "endpoint": endpoint,
            "field_categories": field_categories,
            "content_preview_hash": hashlib.sha256(stable_json(payload).encode()).hexdigest(),
            "payload": payload,
        }

    def start(self, state: ConsentState, *, thread_id: str) -> dict[str, Any]:
        return self.graph.invoke(state, config={"configurable": {"thread_id": thread_id}})

    def resume(self, decision: Literal["approve", "reject"], *, thread_id: str) -> dict[str, Any]:
        return self.graph.invoke(
            Command(resume=decision), config={"configurable": {"thread_id": thread_id}}
        )

    def close(self) -> None:
        self.connection.close()
