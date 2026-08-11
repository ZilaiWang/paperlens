"""Workspace-scoped storage for vNext entities.

Uses the same SQLite file as the V1 Repository (WAL mode). Workspace-owned
tables carry ``workspace_id`` and repository methods require explicit scope;
routes additionally enforce ownership before reads and writes.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path

from paperlens_core.agents.models import ResearchRun
from paperlens_core.autoresearch.experiment import ExperimentRun
from paperlens_core.comparison_v2.models import ComparisonSet
from paperlens_core.research.graph import ResearchEdge, ResearchGraph, ResearchNode
from paperlens_core.research.models import (
    Hypothesis,
    Insight,
    Project,
    ResearchQuestion,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'PERSONAL',
    name TEXT NOT NULL DEFAULT '',
    session_secret TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    goal TEXT NOT NULL DEFAULT '',
    paper_ids TEXT NOT NULL DEFAULT '[]',
    question_ids TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS research_questions (
    question_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    text TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT '[]',
    related_questions TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'OPEN',
    answer TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS hypotheses (
    hypothesis_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    question_id TEXT NOT NULL DEFAULT '',
    statement TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    predictions TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'PROPOSED',
    supporting_evidence TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS insights (
    insight_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    question_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    supporting_papers TEXT NOT NULL DEFAULT '[]',
    evidence TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS research_nodes (
    node_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    node_type TEXT NOT NULL DEFAULT 'NOTE',
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    ref_id TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS research_edges (
    edge_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    edge_type TEXT NOT NULL DEFAULT 'RELATES_TO',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'NOTE',
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS comparison_sets (
    comparison_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    question TEXT NOT NULL DEFAULT '',
    paper_ids TEXT NOT NULL DEFAULT '[]',
    paper_version_ids TEXT NOT NULL DEFAULT '[]',
    versions TEXT NOT NULL DEFAULT '{}',
    dimensions TEXT NOT NULL DEFAULT '[]',
    custom_dimensions TEXT NOT NULL DEFAULT '[]',
    cells TEXT NOT NULL DEFAULT '[]',
    synthesis TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'DRAFT',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS research_runs (
    run_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    question TEXT NOT NULL DEFAULT '',
    tasks TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'PLANNED',
    artifact TEXT NOT NULL DEFAULT '',
    findings TEXT NOT NULL DEFAULT '[]',
    structured_findings TEXT NOT NULL DEFAULT '[]',
    reproduction_requirements TEXT NOT NULL DEFAULT '[]',
    depth TEXT NOT NULL DEFAULT 'ANALYTIC',
    intent TEXT NOT NULL DEFAULT 'GENERAL',
    notes TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS experiment_runs (
    run_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    pack_id TEXT NOT NULL DEFAULT '',
    plan TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'PLANNED',
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    stdout TEXT NOT NULL DEFAULT '',
    exit_code INTEGER,
    artifacts_produced TEXT NOT NULL DEFAULT '[]',
    error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS term_entries (
    workspace_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    source TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    sense TEXT NOT NULL DEFAULT '',
    policy TEXT NOT NULL DEFAULT 'TRANSLATE',
    locked INTEGER NOT NULL DEFAULT 0,
    keep_english INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0.5,
    updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (workspace_id, scope, source)
);
CREATE TABLE IF NOT EXISTS installed_term_packs (
    workspace_id TEXT NOT NULL,
    pack_id TEXT NOT NULL,
    installed_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (workspace_id, pack_id)
);
CREATE TABLE IF NOT EXISTS translation_memory (
    workspace_id TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    normalized_source TEXT NOT NULL,
    translation TEXT NOT NULL,
    language_pair TEXT NOT NULL DEFAULT 'en->zh',
    paper_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    context_snapshot TEXT NOT NULL DEFAULT '',
    quality_score REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (workspace_id, source_hash, language_pair)
);
"""


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str, fallback: object) -> object:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


class VNextRepository:
    """Workspace-scoped vNext storage on the shared SQLite file."""

    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connections = threading.local()
        connection = self._conn
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(SCHEMA)
        self._migrate_workspace_storage()

    @property
    def _conn(self) -> sqlite3.Connection:
        """Return a dedicated SQLite connection for the current worker thread."""
        connection = getattr(self._connections, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.path, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=30000")
            self._connections.connection = connection
        return connection

    @staticmethod
    def _session_digest(token: str) -> str:
        return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _migrate_workspace_storage(self) -> None:
        """Upgrade early vNext tables that accidentally omitted workspace_id."""
        term_columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(term_entries)")
        }
        if "workspace_id" not in term_columns:
            self._conn.executescript(
                """
                ALTER TABLE term_entries RENAME TO term_entries_legacy;
                CREATE TABLE term_entries (
                    workspace_id TEXT NOT NULL, scope TEXT NOT NULL,
                    source TEXT NOT NULL, target TEXT NOT NULL DEFAULT '',
                    domain TEXT NOT NULL DEFAULT '', sense TEXT NOT NULL DEFAULT '',
                    policy TEXT NOT NULL DEFAULT 'TRANSLATE',
                    locked INTEGER NOT NULL DEFAULT 0,
                    keep_english INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    updated_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (workspace_id, scope, source)
                );
                INSERT INTO term_entries
                SELECT 'ws-legacy', scope, source, target, domain, sense, policy,
                       locked, keep_english, confidence, updated_at
                FROM term_entries_legacy;
                DROP TABLE term_entries_legacy;
                """
            )
        memory_columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(translation_memory)")
        }
        if "workspace_id" not in memory_columns:
            self._conn.executescript(
                """
                ALTER TABLE translation_memory RENAME TO translation_memory_legacy;
                CREATE TABLE translation_memory (
                    workspace_id TEXT NOT NULL, source_hash TEXT NOT NULL,
                    normalized_source TEXT NOT NULL, translation TEXT NOT NULL,
                    language_pair TEXT NOT NULL DEFAULT 'en->zh',
                    paper_id TEXT NOT NULL DEFAULT '', project_id TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '', context_snapshot TEXT NOT NULL DEFAULT '',
                    quality_score REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (workspace_id, source_hash, language_pair)
                );
                INSERT INTO translation_memory
                SELECT 'ws-legacy', source_hash, normalized_source, translation,
                       language_pair, paper_id, project_id, model, context_snapshot,
                       quality_score, created_at
                FROM translation_memory_legacy;
                DROP TABLE translation_memory_legacy;
                """
            )
        run_columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(research_runs)")
        }
        run_additions = {
            "structured_findings": "TEXT NOT NULL DEFAULT '[]'",
            "reproduction_requirements": "TEXT NOT NULL DEFAULT '[]'",
            "depth": "TEXT NOT NULL DEFAULT 'ANALYTIC'",
            "intent": "TEXT NOT NULL DEFAULT 'GENERAL'",
        }
        for column, definition in run_additions.items():
            if column not in run_columns:
                self._conn.execute(
                    f"ALTER TABLE research_runs ADD COLUMN {column} {definition}"
                )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Workspaces
    # ------------------------------------------------------------------
    def save_workspace(self, workspace: dict[str, object]) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO workspaces
               (workspace_id, owner_user_id, kind, name, session_secret, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                workspace["workspace_id"],
                workspace.get("owner_user_id", ""),
                workspace.get("kind", "PERSONAL"),
                workspace.get("name", ""),
                self._session_digest(str(workspace.get("session_secret", "")))
                if workspace.get("session_secret")
                and not str(workspace.get("session_secret", "")).startswith("sha256:")
                else workspace.get("session_secret", ""),
                workspace.get("created_at", ""),
            ),
        )
        self._conn.commit()

    def get_workspace(self, workspace_id: str) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_workspace_by_session_token(self, token: str) -> dict[str, object] | None:
        digest = self._session_digest(token)
        row = self._conn.execute(
            "SELECT * FROM workspaces WHERE session_secret IN (?, ?)",
            (digest, token),
        ).fetchone()
        if row is None:
            return None
        if row["session_secret"] == token:
            self._conn.execute(
                "UPDATE workspaces SET session_secret = ? WHERE workspace_id = ?",
                (digest, row["workspace_id"]),
            )
            self._conn.commit()
        return dict(row)

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    def save_project(self, project: Project) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO projects
               (project_id, workspace_id, name, description, goal, paper_ids,
                question_ids, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project.project_id,
                project.workspace_id,
                project.name,
                project.description,
                project.goal,
                _dumps(project.paper_ids),
                _dumps(project.question_ids),
                project.status.value,
                project.created_at,
                project.updated_at,
            ),
        )
        self._conn.commit()

    def get_project(self, project_id: str) -> Project | None:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is None:
            return None
        return Project(
            project_id=row["project_id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            description=row["description"],
            goal=row["goal"],
            paper_ids=_loads(row["paper_ids"], []),
            question_ids=_loads(row["question_ids"], []),
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_projects(self, workspace_id: str) -> list[Project]:
        rows = self._conn.execute(
            "SELECT * FROM projects WHERE workspace_id = ? ORDER BY updated_at DESC",
            (workspace_id,),
        ).fetchall()
        projects: list[Project] = []
        for row in rows:
            projects.append(self.get_project(row["project_id"]))
        return [p for p in projects if p is not None]

    def delete_project(self, project_id: str) -> None:
        self._conn.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
        self._conn.execute("DELETE FROM research_questions WHERE project_id = ?", (project_id,))
        self._conn.execute("DELETE FROM hypotheses WHERE project_id = ?", (project_id,))
        self._conn.execute("DELETE FROM insights WHERE project_id = ?", (project_id,))
        self._conn.execute("DELETE FROM research_nodes WHERE project_id = ?", (project_id,))
        self._conn.execute("DELETE FROM research_edges WHERE project_id = ?", (project_id,))
        self._conn.execute("DELETE FROM artifacts WHERE project_id = ?", (project_id,))
        self._conn.commit()

    # ------------------------------------------------------------------
    # Research questions / hypotheses / insights
    # ------------------------------------------------------------------
    def save_question(self, question: ResearchQuestion) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO research_questions
               (question_id, workspace_id, project_id, text, detail, scope,
                related_questions, status, answer, evidence, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                question.question_id,
                question.workspace_id,
                question.project_id,
                question.text,
                question.detail,
                _dumps(question.scope),
                _dumps(question.related_questions),
                question.status.value,
                question.answer,
                _dumps(question.evidence),
                question.created_at,
                question.updated_at,
            ),
        )
        self._conn.commit()

    def list_questions(self, project_id: str) -> list[ResearchQuestion]:
        rows = self._conn.execute(
            "SELECT * FROM research_questions WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [
            ResearchQuestion(
                question_id=row["question_id"],
                project_id=row["project_id"],
                workspace_id=row["workspace_id"],
                text=row["text"],
                detail=row["detail"],
                scope=_loads(row["scope"], []),
                related_questions=_loads(row["related_questions"], []),
                status=row["status"],
                answer=row["answer"],
                evidence=_loads(row["evidence"], []),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def save_hypothesis(self, hypothesis: Hypothesis) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO hypotheses
               (hypothesis_id, workspace_id, project_id, question_id, statement,
                rationale, predictions, status, supporting_evidence, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                hypothesis.hypothesis_id,
                hypothesis.workspace_id,
                hypothesis.project_id,
                hypothesis.question_id,
                hypothesis.statement,
                hypothesis.rationale,
                _dumps(hypothesis.predictions),
                hypothesis.status.value,
                _dumps(hypothesis.supporting_evidence),
                hypothesis.created_at,
                hypothesis.updated_at,
            ),
        )
        self._conn.commit()

    def list_hypotheses(self, project_id: str) -> list[Hypothesis]:
        rows = self._conn.execute(
            "SELECT * FROM hypotheses WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [
            Hypothesis(
                hypothesis_id=row["hypothesis_id"],
                workspace_id=row["workspace_id"],
                project_id=row["project_id"],
                question_id=row["question_id"],
                statement=row["statement"],
                rationale=row["rationale"],
                predictions=_loads(row["predictions"], []),
                status=row["status"],
                supporting_evidence=_loads(row["supporting_evidence"], []),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def save_insight(self, insight: Insight) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO insights
               (insight_id, workspace_id, project_id, question_id, title, content,
                tags, supporting_papers, evidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                insight.insight_id,
                insight.workspace_id,
                insight.project_id,
                insight.question_id,
                insight.title,
                insight.content,
                _dumps(insight.tags),
                _dumps(insight.supporting_papers),
                _dumps(insight.evidence),
                insight.created_at,
            ),
        )
        self._conn.commit()

    def list_insights(self, project_id: str) -> list[Insight]:
        rows = self._conn.execute(
            "SELECT * FROM insights WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [
            Insight(
                insight_id=row["insight_id"],
                workspace_id=row["workspace_id"],
                project_id=row["project_id"],
                question_id=row["question_id"],
                title=row["title"],
                content=row["content"],
                tags=_loads(row["tags"], []),
                supporting_papers=_loads(row["supporting_papers"], []),
                evidence=_loads(row["evidence"], []),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Research graph
    # ------------------------------------------------------------------
    def save_graph(self, graph: ResearchGraph) -> None:
        for node in graph.nodes:
            self._conn.execute(
                """INSERT OR REPLACE INTO research_nodes
                   (node_id, workspace_id, project_id, node_type, title, content,
                    ref_id, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    node.node_id,
                    "",
                    node.project_id,
                    node.node_type.value,
                    node.title,
                    node.content,
                    node.ref_id,
                    _dumps(node.metadata),
                    node.created_at,
                ),
            )
        for edge in graph.edges:
            self._conn.execute(
                """INSERT OR REPLACE INTO research_edges
                   (edge_id, workspace_id, project_id, source_id, target_id,
                    edge_type, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    edge.edge_id,
                    "",
                    edge.project_id,
                    edge.source_id,
                    edge.target_id,
                    edge.edge_type.value,
                    edge.note,
                    edge.created_at,
                ),
            )
        self._conn.commit()

    def load_graph(self, project_id: str) -> ResearchGraph:
        node_rows = self._conn.execute(
            "SELECT * FROM research_nodes WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        edge_rows = self._conn.execute(
            "SELECT * FROM research_edges WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        nodes = [
            ResearchNode(
                node_id=row["node_id"],
                project_id=row["project_id"],
                node_type=row["node_type"],
                title=row["title"],
                content=row["content"],
                ref_id=row["ref_id"],
                metadata=_loads(row["metadata"], {}),
                created_at=row["created_at"],
            )
            for row in node_rows
        ]
        edges = [
            ResearchEdge(
                edge_id=row["edge_id"],
                project_id=row["project_id"],
                source_id=row["source_id"],
                target_id=row["target_id"],
                edge_type=row["edge_type"],
                note=row["note"],
                created_at=row["created_at"],
            )
            for row in edge_rows
        ]
        return ResearchGraph(project_id=project_id, nodes=nodes, edges=edges)

    # ------------------------------------------------------------------
    # Comparison sets
    # ------------------------------------------------------------------
    def save_comparison_set(self, comparison: ComparisonSet) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO comparison_sets
               (comparison_id, workspace_id, name, description, question, paper_ids,
                paper_version_ids, versions, dimensions, custom_dimensions, cells,
                synthesis, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                comparison.comparison_id,
                comparison.workspace_id,
                comparison.name,
                comparison.description,
                comparison.question,
                _dumps(comparison.paper_ids),
                _dumps(comparison.paper_version_ids),
                _dumps({k: v.model_dump(mode="json") for k, v in comparison.versions.items()}),
                _dumps(comparison.dimensions),
                _dumps([c.model_dump(mode="json") for c in comparison.custom_dimensions]),
                _dumps([c.model_dump(mode="json") for c in comparison.cells]),
                _dumps(comparison.synthesis.model_dump(mode="json")),
                comparison.status.value,
                comparison.created_at,
                comparison.updated_at,
            ),
        )
        self._conn.commit()

    def get_comparison_set(self, comparison_id: str) -> ComparisonSet | None:
        row = self._conn.execute(
            "SELECT * FROM comparison_sets WHERE comparison_id = ?", (comparison_id,)
        ).fetchone()
        if row is None:
            return None
        from paperlens_core.comparison_v2.extraction import CustomDimension
        from paperlens_core.comparison_v2.models import ComparisonVersion

        versions = _loads(row["versions"], {})
        custom = [_loads(item, {}) for item in _loads(row["custom_dimensions"], [])]
        cells = [_loads(item, {}) for item in _loads(row["cells"], [])]
        synthesis = _loads(row["synthesis"], {}) or {}
        return ComparisonSet(
            comparison_id=row["comparison_id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            description=row["description"],
            question=row["question"],
            paper_ids=_loads(row["paper_ids"], []),
            paper_version_ids=_loads(row["paper_version_ids"], []),
            versions={
                key: ComparisonVersion.model_validate(value)
                for key, value in versions.items()
                if isinstance(value, dict)
            },
            dimensions=_loads(row["dimensions"], []),
            custom_dimensions=[
                CustomDimension(**item) for item in custom if isinstance(item, dict) and item
            ],
            cells=[item for item in cells if isinstance(item, dict)],
            synthesis=_loads(synthesis, {}),
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_comparison_sets(self, workspace_id: str) -> list[ComparisonSet]:
        rows = self._conn.execute(
            "SELECT comparison_id FROM comparison_sets WHERE workspace_id = ? ORDER BY updated_at DESC",
            (workspace_id,),
        ).fetchall()
        sets: list[ComparisonSet] = []
        for row in rows:
            comparison = self.get_comparison_set(row["comparison_id"])
            if comparison is not None:
                sets.append(comparison)
        return sets

    def delete_comparison_set(self, comparison_id: str) -> None:
        self._conn.execute(
            "DELETE FROM comparison_sets WHERE comparison_id = ?", (comparison_id,)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Research runs
    # ------------------------------------------------------------------
    def save_run(self, run: ResearchRun) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO research_runs
               (run_id, workspace_id, project_id, question, tasks, status, artifact,
                findings, structured_findings, reproduction_requirements, depth,
                intent, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run.run_id,
                run.workspace_id,
                run.project_id,
                run.question,
                _dumps([t.model_dump(mode="json") for t in run.tasks]),
                run.status.value,
                _dumps(run.artifact.model_dump(mode="json")) if run.artifact else "",
                _dumps(run.findings),
                _dumps([item.model_dump(mode="json") for item in run.structured_findings]),
                _dumps([item.model_dump(mode="json") for item in run.reproduction_requirements]),
                run.depth.value,
                run.intent,
                _dumps(run.notes),
                run.created_at,
                run.updated_at,
            ),
        )
        self._conn.commit()

    def get_run(self, run_id: str) -> ResearchRun | None:
        row = self._conn.execute(
            "SELECT * FROM research_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        from paperlens_core.agents.models import (
            ArtifactProduced,
            ReproductionRequirement,
            ResearchFinding,
            TaskDefinition,
        )

        artifact_data = _loads(row["artifact"], None) if row["artifact"] else None
        return ResearchRun(
            run_id=row["run_id"],
            workspace_id=row["workspace_id"],
            project_id=row["project_id"],
            question=row["question"],
            tasks=[
                TaskDefinition(**item) for item in _loads(row["tasks"], [])
                if isinstance(item, dict) and item
            ],
            status=row["status"],
            artifact=ArtifactProduced(**artifact_data) if artifact_data else None,
            findings=_loads(row["findings"], []),
            structured_findings=[
                ResearchFinding(**item)
                for item in _loads(row["structured_findings"], [])
                if isinstance(item, dict)
            ],
            reproduction_requirements=[
                ReproductionRequirement(**item)
                for item in _loads(row["reproduction_requirements"], [])
                if isinstance(item, dict)
            ],
            depth=row["depth"],
            intent=row["intent"],
            notes=_loads(row["notes"], []),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_runs(self, project_id: str) -> list[ResearchRun]:
        rows = self._conn.execute(
            "SELECT run_id FROM research_runs WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
        runs: list[ResearchRun] = []
        for row in rows:
            run = self.get_run(row["run_id"])
            if run is not None:
                runs.append(run)
        return runs

    # ------------------------------------------------------------------
    # Experiment runs
    # ------------------------------------------------------------------
    def save_experiment_run(self, run: ExperimentRun) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO experiment_runs
               (run_id, workspace_id, project_id, pack_id, plan, status, started_at,
                finished_at, stdout, exit_code, artifacts_produced, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run.run_id,
                run.workspace_id,
                run.project_id,
                run.pack_id,
                _dumps(run.plan.model_dump(mode="json")),
                run.status.value,
                run.started_at,
                run.finished_at,
                run.stdout,
                run.exit_code,
                _dumps(run.artifacts_produced),
                run.error,
            ),
        )
        self._conn.commit()

    def list_experiment_runs(self, project_id: str) -> list[ExperimentRun]:
        rows = self._conn.execute(
            "SELECT * FROM experiment_runs WHERE project_id = ? ORDER BY started_at DESC",
            (project_id,),
        ).fetchall()
        from paperlens_core.autoresearch.experiment import ExperimentPlan

        return [
            ExperimentRun(
                run_id=row["run_id"],
                workspace_id=row["workspace_id"],
                project_id=row["project_id"],
                pack_id=row["pack_id"],
                plan=ExperimentPlan(**_loads(row["plan"], {})),
                status=row["status"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                stdout=row["stdout"],
                exit_code=row["exit_code"],
                artifacts_produced=_loads(row["artifacts_produced"], []),
                error=row["error"],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Termbase entries
    # ------------------------------------------------------------------
    def save_term_entry(self, workspace_id: str, entry: dict[str, object]) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO term_entries
               (workspace_id, scope, source, target, domain, sense, policy, locked, keep_english,
                confidence, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                workspace_id,
                entry["scope"],
                entry["source"],
                entry.get("target", ""),
                entry.get("domain", ""),
                entry.get("sense", ""),
                entry.get("policy", "TRANSLATE"),
                1 if entry.get("locked") else 0,
                1 if entry.get("keep_english") else 0,
                entry.get("confidence", 0.5),
                entry.get("updated_at", ""),
            ),
        )
        self._conn.commit()

    def list_term_entries(
        self, workspace_id: str, scope: str | None = None
    ) -> list[dict[str, object]]:
        if scope:
            rows = self._conn.execute(
                "SELECT * FROM term_entries WHERE workspace_id = ? AND scope = ? ORDER BY source",
                (workspace_id, scope),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM term_entries WHERE workspace_id = ? ORDER BY scope, source",
                (workspace_id,),
            ).fetchall()
        return [
            {
                "scope": row["scope"],
                "source": row["source"],
                "target": row["target"],
                "domain": row["domain"],
                "sense": row["sense"],
                "policy": row["policy"],
                "locked": bool(row["locked"]),
                "keep_english": bool(row["keep_english"]),
                "confidence": row["confidence"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def delete_term_entry(self, workspace_id: str, scope: str, source: str) -> None:
        self._conn.execute(
            "DELETE FROM term_entries WHERE workspace_id = ? AND scope = ? AND source = ?",
            (workspace_id, scope, source),
        )
        self._conn.commit()

    def list_installed_term_packs(self, workspace_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT pack_id FROM installed_term_packs WHERE workspace_id = ? ORDER BY installed_at",
            (workspace_id,),
        ).fetchall()
        return [row["pack_id"] for row in rows]

    def install_term_pack(self, workspace_id: str, pack_id: str, installed_at: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO installed_term_packs (workspace_id, pack_id, installed_at) VALUES (?, ?, ?)",
            (workspace_id, pack_id, installed_at),
        )
        self._conn.commit()

    def uninstall_term_pack(self, workspace_id: str, pack_id: str) -> None:
        self._conn.execute(
            "DELETE FROM installed_term_packs WHERE workspace_id = ? AND pack_id = ?",
            (workspace_id, pack_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Translation memory
    # ------------------------------------------------------------------
    def save_memory_entry(self, workspace_id: str, entry: dict[str, object]) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO translation_memory
               (workspace_id, source_hash, normalized_source, translation, language_pair, paper_id,
                project_id, model, context_snapshot, quality_score, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                workspace_id,
                entry["source_hash"],
                entry.get("normalized_source", ""),
                entry.get("translation", ""),
                entry.get("language_pair", "en->zh"),
                entry.get("paper_id", ""),
                entry.get("project_id", ""),
                entry.get("model", ""),
                entry.get("context_snapshot", ""),
                entry.get("quality_score", 0.0),
                entry.get("created_at", ""),
            ),
        )
        self._conn.commit()

    def memory_entries(self, workspace_id: str, limit: int = 500) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT * FROM translation_memory WHERE workspace_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (workspace_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]
