"""Research service: run Research Agent DAGs, persist runs and artifacts.

The agent tools are wired to the real data layer (Repository for chunks,
ProfileBuilder, comparison alignment) so a run is genuinely executable, not a
demonstration.
"""

from __future__ import annotations

from typing import Any

from paperlens_core.agents.executor import execute_run
from paperlens_core.agents.models import ResearchRun
from paperlens_core.agents.planner import create_run_plan
from paperlens_core.agents.tools import build_default_registry
from paperlens_core.comparison_v2.alignment import align_results
from paperlens_core.comparison_v2.comparability import result_record_from_profile
from paperlens_core.ir.identity import new_id
from paperlens_core.papers.profile_builder import PaperProfileBuilder
from paperlens_core.retrieval.lexical import TextUnit

from ..repositories import VNextRepository
from ..repository import Repository, now_iso


class ResearchService:
    """Orchestrate agent runs backed by the real document repository."""

    def __init__(self, repository: Repository, vnext: VNextRepository):
        self.repository = repository
        self.vnext = vnext

    # ------------------------------------------------------------------
    def _corpus(self, paper_version_ids: list[str]) -> list[TextUnit]:
        """Build a TextUnit corpus from stored chunks."""
        from paperlens_core.documents import Chunk

        units: list[TextUnit] = []
        for version_id in paper_version_ids:
            try:
                chunk_items = self.repository.load_document(version_id, "chunks")
            except Exception:  # noqa: BLE001 - a missing version is not fatal
                continue
            for item in chunk_items:
                try:
                    chunk = Chunk.model_validate(item)
                except Exception:  # noqa: BLE001 - skip malformed rows
                    continue
                units.append(
                    TextUnit(
                        unit_id=f"{version_id}:{chunk.chunk_id}",
                        paper_version_id=version_id,
                        text=chunk.text,
                        section_path=chunk.section_path,
                        page=chunk.page_start,
                    )
                )
        return units

    def create_run(self, *, workspace_id: str, project_id: str, question: str, paper_version_ids: list[str] | None = None) -> ResearchRun:
        created = now_iso()
        run = create_run_plan(
            run_id=new_id("run"),
            workspace_id=workspace_id,
            project_id=project_id,
            question=question,
            scope_paper_ids=paper_version_ids or [],
            created_at=created,
        )
        self.vnext.save_run(run)
        return run

    def execute(self, run: ResearchRun) -> dict[str, Any]:
        corpus = self._corpus(_parameters_scope(run))
        registry = build_default_registry(
            corpus=corpus,
            profile_fn=self._profile_payloads,
            compare_fn=self._compare_versions,
        )
        results = execute_run(run, registry=registry)
        run.updated_at = now_iso()
        self.vnext.save_run(run)
        return {
            "run_id": run.run_id,
            "status": run.status.value,
            "task_count": len(results),
            "ok_count": sum(1 for r in results if r.ok),
            "artifact": run.artifact.model_dump(mode="json") if run.artifact else None,
            "findings": run.findings,
            "tasks": [r.model_dump(mode="json") for r in results],
        }

    def list_runs(self, project_id: str) -> list[ResearchRun]:
        return self.vnext.list_runs(project_id)

    def get_run(self, run_id: str) -> ResearchRun | None:
        return self.vnext.get_run(run_id)

    def _profile_payloads(self, version_ids: list[str]) -> list[dict[str, object]]:
        builder = PaperProfileBuilder()
        payloads: list[dict[str, object]] = []
        for version_id in version_ids:
            blocks = self.repository.load_document(version_id, "blocks")
            meta_items = self.repository.load_document(version_id, "paper_meta")
            meta = meta_items[0] if meta_items else {}
            profile = builder.build_offline(
                paper_id=str(meta.get("paper_id", version_id)),
                paper_version_id=version_id,
                title=str(meta.get("title", "")),
                abstract=str(meta.get("abstract", "")),
                blocks=[type("StoredBlock", (), item)() for item in blocks],
            )
            payloads.append(profile.model_dump(mode="json"))
        return payloads

    def _compare_versions(self, version_ids: list[str]) -> dict[str, object]:
        records = []
        for payload in self._profile_payloads(version_ids):
            from paperlens_core.papers.models import PaperProfile

            profile = PaperProfile.model_validate(payload)
            records.extend(result_record_from_profile(profile))
        return {"matrix": align_results(records).as_matrix(), "record_count": len(records)}


def _parameters_scope(run: ResearchRun) -> list[str]:
    """Collect paper ids referenced by any task params."""
    scope: list[str] = []
    for task in run.tasks:
        paper_ids = task.params.get("paper_ids")
        if isinstance(paper_ids, list):
            scope.extend(paper_ids)
    return scope
