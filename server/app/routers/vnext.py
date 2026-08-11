"""vNext API routes (改进方案2 Phase A / G / H / I).

Thin routes: workspace resolution, service calls, JSON out.  All heavy logic
lives in ``services`` and ``repositories`` so the routes stay auditable.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from paperlens_core.autoresearch.context import build_research_context_pack
from paperlens_core.autoresearch.experiment import (
    ExperimentPlan,
    create_experiment_run,
)
from paperlens_core.comparison_v2.alignment import align_results
from paperlens_core.comparison_v2.comparability import (
    ResultRecord,
    result_record_from_profile,
)
from paperlens_core.comparison_v2.models import ComparisonSet, ComparisonStatus
from paperlens_core.comparison_v2.synthesis import Synthesizer
from paperlens_core.ir.identity import new_id
from paperlens_core.papers.profile_builder import PaperProfileBuilder
from paperlens_core.research.models import Hypothesis, Project, ResearchQuestion
from paperlens_core.termbase import TermPackCatalog, TermResolver, TermScope

from ..auth import resolve_workspace_id, set_session_cookie
from ..repositories import VNextRepository
from ..repository import now_iso
from ..schemas import (
    ComparisonSetCreateRequest,
    ExperimentPlanRequest,
    HypothesisCreateRequest,
    ProjectCreateRequest,
    ProjectPaperRequest,
    ProjectUpdateRequest,
    QuestionCreateRequest,
    RunCreateRequest,
    TermScanRequest,
    TermUpsertRequest,
    TranslateV2Request,
    WorkspaceCreateRequest,
)
from ..services.projects import ProjectService
from ..services.research import ResearchService
from ..services.translation_v2 import TranslationV2Service
from ..services.workspace import WorkspaceService

logger = logging.getLogger("paperlens.vnext")

router = APIRouter(prefix="/api/v2", tags=["v2"])


# ---------------------------------------------------------------------------
# Shared dependencies (lazily built once per app; overridable in tests)
# ---------------------------------------------------------------------------
def _vnext_repo() -> VNextRepository:
    from ..main import vnext_repository

    return vnext_repository


def _workspace_service() -> WorkspaceService:
    return WorkspaceService(_vnext_repo())


def _project_service() -> ProjectService:
    return ProjectService(_vnext_repo())


def _research_service() -> ResearchService:
    from ..main import research_service

    return research_service


def _translation_v2_service() -> TranslationV2Service:
    return TranslationV2Service(_vnext_repo())


def _ws(request: Request) -> str:
    return resolve_workspace_id(request, _vnext_repo())


# ---------------------------------------------------------------------------
# Workspace identity (改进方案2 §51)
# ---------------------------------------------------------------------------
@router.post("/workspaces/anonymous")
def create_anonymous_workspace(
    request: Request,
    response: Response,
    payload: WorkspaceCreateRequest | None = None,
    service: WorkspaceService = Depends(_workspace_service),
) -> dict[str, object]:
    name = payload.name if payload else ""
    workspace = service.create_anonymous(name=name)
    set_session_cookie(response, workspace.session_secret)
    return {
        "workspace_id": workspace.workspace_id,
        "name": workspace.name,
        "kind": workspace.kind.value,
        "created_at": workspace.created_at,
    }


@router.get("/workspaces/me")
def get_workspace(
    request: Request,
    service: WorkspaceService = Depends(_workspace_service),
) -> dict[str, object]:
    workspace_id = _ws(request)
    workspace = service.get(workspace_id)
    if workspace is None:
        raise HTTPException(401, "invalid workspace session")
    return {
        "workspace_id": workspace.workspace_id,
        "name": workspace.name,
        "kind": workspace.kind.value,
        "created_at": workspace.created_at,
    }


# ---------------------------------------------------------------------------
# Projects (改进方案2 §39-43)
# ---------------------------------------------------------------------------
@router.get("/projects")
def list_projects(
    request: Request,
    service: ProjectService = Depends(_project_service),
) -> list[dict[str, object]]:
    return [
        _project_dict(project)
        for project in service.list_projects(_ws(request))
    ]


@router.post("/projects")
def create_project(
    request: Request,
    payload: ProjectCreateRequest,
    service: ProjectService = Depends(_project_service),
) -> dict[str, object]:
    project = service.create_project(
        workspace_id=_ws(request),
        name=payload.name,
        description=payload.description,
        goal=payload.goal,
    )
    return _project_dict(project)


@router.get("/projects/{project_id}")
def get_project(
    project_id: str,
    request: Request,
    service: ProjectService = Depends(_project_service),
) -> dict[str, object]:
    project = service.repository.get_project(project_id)
    if project is None or project.workspace_id != _ws(request):
        raise HTTPException(404, "project not found")
    return _project_dict(project)


@router.patch("/projects/{project_id}")
def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    request: Request,
    service: ProjectService = Depends(_project_service),
) -> dict[str, object]:
    project = service.repository.get_project(project_id)
    if project is None or project.workspace_id != _ws(request):
        raise HTTPException(404, "project not found")
    updated = service.update_project(
        project_id,
        name=payload.name,
        description=payload.description,
        goal=payload.goal,
    )
    return _project_dict(updated)


@router.post("/projects/{project_id}/papers")
def add_project_paper(
    project_id: str,
    payload: ProjectPaperRequest,
    request: Request,
    service: ProjectService = Depends(_project_service),
) -> dict[str, object]:
    project = service.repository.get_project(project_id)
    if project is None or project.workspace_id != _ws(request):
        raise HTTPException(404, "project not found")
    updated = service.add_paper(project_id, payload.paper_id)
    return _project_dict(updated)


@router.delete("/projects/{project_id}")
def delete_project(
    project_id: str,
    request: Request,
    service: ProjectService = Depends(_project_service),
) -> dict[str, object]:
    project = service.repository.get_project(project_id)
    if project is None or project.workspace_id != _ws(request):
        raise HTTPException(404, "project not found")
    service.delete_project(project_id)
    return {"deleted": project_id}


# ---------------------------------------------------------------------------
# Research questions / hypotheses (改进方案2 §41-42)
# ---------------------------------------------------------------------------
@router.post("/projects/{project_id}/questions")
def create_question(
    project_id: str,
    payload: QuestionCreateRequest,
    request: Request,
    service: ProjectService = Depends(_project_service),
) -> dict[str, object]:
    _assert_project_owner(project_id, _ws(request), service)
    question = service.create_question(
        workspace_id=_ws(request),
        project_id=project_id,
        text=payload.text,
        detail=payload.detail,
    )
    return _question_dict(question)


@router.get("/projects/{project_id}/questions")
def list_questions(
    project_id: str,
    request: Request,
    service: ProjectService = Depends(_project_service),
) -> list[dict[str, object]]:
    _assert_project_owner(project_id, _ws(request), service)
    return [_question_dict(q) for q in service.list_questions(project_id)]


@router.post("/projects/{project_id}/hypotheses")
def create_hypothesis(
    project_id: str,
    payload: HypothesisCreateRequest,
    request: Request,
    service: ProjectService = Depends(_project_service),
) -> dict[str, object]:
    _assert_project_owner(project_id, _ws(request), service)
    hypothesis = service.create_hypothesis(
        workspace_id=_ws(request),
        project_id=project_id,
        question_id=payload.question_id,
        statement=payload.statement,
        rationale=payload.rationale,
    )
    return _hypothesis_dict(hypothesis)


@router.get("/projects/{project_id}/hypotheses")
def list_hypotheses(
    project_id: str,
    request: Request,
    service: ProjectService = Depends(_project_service),
) -> list[dict[str, object]]:
    _assert_project_owner(project_id, _ws(request), service)
    return [_hypothesis_dict(h) for h in service.list_hypotheses(project_id)]


# ---------------------------------------------------------------------------
# Research graph (改进方案2 §40)
# ---------------------------------------------------------------------------
@router.get("/projects/{project_id}/graph")
def get_graph(
    project_id: str,
    request: Request,
    service: ProjectService = Depends(_project_service),
) -> dict[str, object]:
    _assert_project_owner(project_id, _ws(request), service)
    graph = service.repository.load_graph(project_id)
    return {
        "project_id": project_id,
        "nodes": [n.model_dump(mode="json") for n in graph.nodes],
        "edges": [e.model_dump(mode="json") for e in graph.edges],
    }


# ---------------------------------------------------------------------------
# Research runs (改进方案2 Phase H)
# ---------------------------------------------------------------------------
@router.post("/projects/{project_id}/runs")
def create_run(
    project_id: str,
    payload: RunCreateRequest,
    request: Request,
    service: ResearchService = Depends(_research_service),
) -> dict[str, object]:
    workspace_id = _ws(request)
    _assert_project_owner(project_id, workspace_id, ProjectService(_vnext_repo()))
    run = service.create_run(
        workspace_id=workspace_id,
        project_id=project_id,
        question=payload.question,
        paper_version_ids=payload.paper_version_ids,
    )
    return _run_dict(run)


@router.post("/projects/{project_id}/runs/{run_id}/execute")
def execute_run_route(
    project_id: str,
    run_id: str,
    request: Request,
    service: ResearchService = Depends(_research_service),
) -> dict[str, object]:
    workspace_id = _ws(request)
    _assert_project_owner(project_id, workspace_id, ProjectService(_vnext_repo()))
    run = service.get_run(run_id)
    if run is None or run.project_id != project_id:
        raise HTTPException(404, "run not found")
    return service.execute(run)


@router.get("/projects/{project_id}/runs")
def list_runs(
    project_id: str,
    request: Request,
    service: ResearchService = Depends(_research_service),
) -> list[dict[str, object]]:
    _assert_project_owner(project_id, _ws(request), ProjectService(_vnext_repo()))
    return [_run_dict(r) for r in service.list_runs(project_id)]


@router.get("/projects/{project_id}/runs/{run_id}")
def get_run_route(
    project_id: str,
    run_id: str,
    request: Request,
    service: ResearchService = Depends(_research_service),
) -> dict[str, object]:
    _assert_project_owner(project_id, _ws(request), ProjectService(_vnext_repo()))
    run = service.get_run(run_id)
    if run is None or run.project_id != project_id:
        raise HTTPException(404, "run not found")
    return _run_dict(run)


# ---------------------------------------------------------------------------
# Comparison sets v2 (改进方案2 Phase F)
# ---------------------------------------------------------------------------
@router.get("/comparison-sets")
def list_comparison_sets(
    request: Request,
    repo: VNextRepository = Depends(_vnext_repo),
) -> list[dict[str, object]]:
    return [
        _comparison_dict(c)
        for c in repo.list_comparison_sets(_ws(request))
    ]


@router.post("/comparison-sets")
def create_comparison_set(
    payload: ComparisonSetCreateRequest,
    request: Request,
    repo: VNextRepository = Depends(_vnext_repo),
) -> dict[str, object]:
    created = now_iso()
    comparison = ComparisonSet(
        comparison_id=new_id("cmp"),
        workspace_id=_ws(request),
        name=payload.name,
        description=payload.description,
        question=payload.question,
        paper_version_ids=payload.paper_version_ids,
        dimensions=payload.dimensions or [
            "problem", "method", "experiments", "result_summary"
        ],
        status=ComparisonStatus.DRAFT,
        created_at=created,
        updated_at=created,
    )
    for version_id in payload.paper_version_ids:
        comparison.ensure_paper(version_id, version_id)
    if payload.custom_dimensions:
        from paperlens_core.comparison_v2.extraction import CustomDimension

        comparison.custom_dimensions = [
            CustomDimension(name=item.name, instruction=item.instruction)
            for item in payload.custom_dimensions
        ]
    repo.save_comparison_set(comparison)
    return _comparison_dict(comparison)


@router.get("/comparison-sets/{comparison_id}")
def get_comparison_set(
    comparison_id: str,
    request: Request,
    repo: VNextRepository = Depends(_vnext_repo),
) -> dict[str, object]:
    comparison = _owned_comparison(comparison_id, _ws(request), repo)
    return _comparison_dict(comparison)


@router.post("/comparison-sets/{comparison_id}/align")
def align_comparison_set(
    comparison_id: str,
    request: Request,
    repo: VNextRepository = Depends(_vnext_repo),
) -> dict[str, object]:
    comparison = _owned_comparison(comparison_id, _ws(request), repo)
    records: list[ResultRecord] = []
    from ..main import repository

    builder = PaperProfileBuilder()
    for version_id in comparison.paper_version_ids:
        profile = _profile_for_version(builder, repository, version_id)
        if profile is not None:
            records.extend(result_record_from_profile(profile, paper_version_id=version_id))
    table = align_results(records)
    return {"comparison_id": comparison_id, "matrix": table.as_matrix()}


@router.post("/comparison-sets/{comparison_id}/synthesize")
def synthesize_comparison_set(
    comparison_id: str,
    request: Request,
    repo: VNextRepository = Depends(_vnext_repo),
) -> dict[str, object]:
    comparison = _owned_comparison(comparison_id, _ws(request), repo)
    synthesizer = Synthesizer(model=None)  # offline synthesis (gaps/consensus)
    comparison.synthesis = synthesizer.synthesize(comparison)
    comparison.status = ComparisonStatus.SYNTHESIZED
    comparison.updated_at = now_iso()
    repo.save_comparison_set(comparison)
    return _comparison_dict(comparison)


@router.delete("/comparison-sets/{comparison_id}")
def delete_comparison_set(
    comparison_id: str,
    request: Request,
    repo: VNextRepository = Depends(_vnext_repo),
) -> dict[str, object]:
    _owned_comparison(comparison_id, _ws(request), repo)
    repo.delete_comparison_set(comparison_id)
    return {"deleted": comparison_id}


# ---------------------------------------------------------------------------
# Termbase (改进方案2 §21-22)
# ---------------------------------------------------------------------------
@router.get("/termbase")
def list_termbase(
    request: Request,
    repo: VNextRepository = Depends(_vnext_repo),
) -> list[dict[str, object]]:
    custom = repo.list_term_entries(_ws(request), scope=None)
    system = [
        entry.model_dump(mode="json") for entry in TermResolver().system.all()
    ]
    return custom + system


@router.post("/termbase")
def upsert_term(
    payload: TermUpsertRequest,
    request: Request,
    repo: VNextRepository = Depends(_vnext_repo),
) -> dict[str, object]:
    if payload.scope in {TermScope.SYSTEM, TermScope.DOMAIN}:
        raise HTTPException(403, "system and domain terms are read-only")
    workspace_id = _ws(request)
    entry = {
        "scope": payload.scope.value,
        "source": payload.source,
        "target": payload.target,
        "domain": payload.domain,
        "sense": payload.sense,
        "policy": payload.policy.value,
        "locked": payload.locked,
        "keep_english": payload.keep_english,
        "confidence": 0.9 if payload.locked else 0.7,
        "updated_at": now_iso(),
    }
    repo.save_term_entry(workspace_id, entry)
    return entry


@router.delete("/termbase/{scope}/{source}")
def delete_term(
    scope: str,
    source: str,
    request: Request,
    repo: VNextRepository = Depends(_vnext_repo),
) -> dict[str, object]:
    repo.delete_term_entry(_ws(request), scope, source)
    return {"deleted": f"{scope}:{source}"}


@router.get("/term-packs")
def list_term_packs(
    request: Request,
    repo: VNextRepository = Depends(_vnext_repo),
) -> list[dict[str, object]]:
    installed = set(repo.list_installed_term_packs(_ws(request)))
    return [
        {**manifest.model_dump(mode="json"), "installed": manifest.pack_id in installed}
        for manifest in TermPackCatalog().list()
    ]


@router.post("/term-packs/{pack_id}/install")
def install_term_pack(
    pack_id: str,
    request: Request,
    repo: VNextRepository = Depends(_vnext_repo),
) -> dict[str, object]:
    pack = TermPackCatalog().get(pack_id)
    if pack is None:
        raise HTTPException(404, "term pack not found")
    repo.install_term_pack(_ws(request), pack_id, now_iso())
    return {**pack.manifest.model_dump(mode="json"), "installed": True}


@router.delete("/term-packs/{pack_id}")
def uninstall_term_pack(
    pack_id: str,
    request: Request,
    repo: VNextRepository = Depends(_vnext_repo),
) -> dict[str, object]:
    repo.uninstall_term_pack(_ws(request), pack_id)
    return {"pack_id": pack_id, "installed": False}


# ---------------------------------------------------------------------------
# Translation memory (改进方案2 §23)
# ---------------------------------------------------------------------------
@router.get("/translation-memory")
def list_memory(
    request: Request,
    repo: VNextRepository = Depends(_vnext_repo),
) -> list[dict[str, object]]:
    return repo.memory_entries(_ws(request), limit=500)


# ---------------------------------------------------------------------------
# Translation v2 (改进方案2 Phase D)
# ---------------------------------------------------------------------------
@router.post("/translations/v2")
def translate_v2(
    payload: TranslateV2Request,
    request: Request,
    service: TranslationV2Service = Depends(_translation_v2_service),
) -> dict[str, object]:
    """Six-stage translation with termbase + memory (改进方案2 §24).

    Model is wired lazily from Settings; if no API key is configured the
    endpoint still runs the deterministic stages and reports that the model
    stage is unavailable.
    """
    from paperlens_core.config import Settings
    from paperlens_core.llm import OpenAICompatibleModel

    workspace_id = _ws(request)
    try:
        settings = Settings()
        model = OpenAICompatibleModel(settings)
        model_ok = settings.llm_configured
    except Exception:  # noqa: BLE001 - offline/keys missing is a supported mode
        model = None
        model_ok = False

    engine = service.build_engine(model, workspace_id) if model is not None and model_ok else None
    if engine is None:
        # deterministic-only pass: report stage availability, no model call
        return {
            "workspace_id": workspace_id,
            "model_available": False,
            "translations": payload.paragraphs,
            "issues": [[] for _ in payload.paragraphs],
            "stages_run": ["CONTEXT", "TERMS", "PROTECT"],
            "note": "未配置 LLM API Key——未执行模型翻译阶段",
        }

    try:
        result = engine.translate_paragraphs(
            paragraphs=payload.paragraphs,
            section_title=payload.section_title,
            paper_title=payload.paper_title,
            thread_id=f"trans-v2-{workspace_id[:8]}",
        )
    except Exception as exc:  # noqa: BLE001 - model outage degrades to source text
        logger.warning("translation v2 model unavailable: %s", exc)
        return {
            "workspace_id": workspace_id,
            "model_available": False,
            "translations": payload.paragraphs,
            "issues": [[] for _ in payload.paragraphs],
            "stages_run": ["CONTEXT", "TERMS", "PROTECT"],
            "note": "LLM 暂时不可用——已保留原文，可稍后重试",
        }
    return {
        "workspace_id": workspace_id,
        "model_available": True,
        "translations": result.translations,
        "issues": result.issues,
        "repaired_indices": result.repaired_indices,
        "memory_hits": result.memory_hits,
        "stages_run": result.stages_run,
        "term_snapshot": result.term_snapshot,
    }


@router.post("/translations/scan-terms")
def scan_terms(
    payload: TermScanRequest,
    request: Request,
    service: TranslationV2Service = Depends(_translation_v2_service),
) -> dict[str, object]:
    """Return every known term occurrence in a text (UI hover data)."""
    hits = service.resolve_terms_in_text(_ws(request), payload.text)
    return {"terms": hits, "count": len(hits)}


# ---------------------------------------------------------------------------
# AutoResearch bridge (改进方案2 Phase I)
# ---------------------------------------------------------------------------
@router.post("/projects/{project_id}/context-pack")
def build_context_pack(
    project_id: str,
    request: Request,
    service: ProjectService = Depends(_project_service),
) -> dict[str, object]:
    workspace_id = _ws(request)
    project = _assert_project_owner(project_id, workspace_id, service)
    questions = service.list_questions(project_id)
    hypotheses = service.list_hypotheses(project_id)
    pack = build_research_context_pack(
        pack_id=new_id("pack"),
        workspace_id=workspace_id,
        project_id=project_id,
        project_name=project.name,
        goal=project.goal,
        questions=[q.text for q in questions],
        hypotheses=[
            {"id": h.hypothesis_id, "statement": h.statement, "status": h.status.value}
            for h in hypotheses
        ],
        created_at=now_iso(),
    )
    return pack.as_dict()


@router.post("/projects/{project_id}/experiment-runs")
def create_experiment_run_route(
    project_id: str,
    payload: ExperimentPlanRequest,
    request: Request,
    service: ProjectService = Depends(_project_service),
) -> dict[str, object]:
    workspace_id = _ws(request)
    _assert_project_owner(project_id, workspace_id, service)
    run = create_experiment_run(
        run_id=new_id("erun"),
        workspace_id=workspace_id,
        project_id=project_id,
        plan=ExperimentPlan(
            run_id=new_id("erun"),
            kind=payload.kind,
            command=payload.command,
            description=payload.description,
            parameters=payload.parameters,
        ),
        started_at=now_iso(),
    )
    repo = _vnext_repo()
    repo.save_experiment_run(run)
    return run.model_dump(mode="json")


@router.get("/projects/{project_id}/experiment-runs")
def list_experiment_runs(
    project_id: str,
    request: Request,
    service: ProjectService = Depends(_project_service),
) -> list[dict[str, object]]:
    _assert_project_owner(project_id, _ws(request), service)
    return [
        r.model_dump(mode="json")
        for r in _vnext_repo().list_experiment_runs(project_id)
    ]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _owned_comparison(
    comparison_id: str,
    workspace_id: str,
    repo: VNextRepository,
) -> ComparisonSet:
    comparison = repo.get_comparison_set(comparison_id)
    if comparison is None or comparison.workspace_id != workspace_id:
        raise HTTPException(404, "comparison set not found")
    return comparison


def _profile_for_version(builder: PaperProfileBuilder, repository: object, version_id: str):
    """Build an offline profile from stored blocks/meta, best-effort."""
    try:
        meta_items = repository.load_document(version_id, "paper_meta")
        meta = meta_items[0] if meta_items else {}
        sections: dict[str, str] = {}
        section_items = repository.load_document(version_id, "sections")
        for item in section_items:
            name = item.get("title") or item.get("section_id") or "Section"
            sections[str(name)] = str(item.get("summary", ""))
        return builder.build_offline(
            paper_id=str(meta.get("paper_id", version_id)),
            paper_version_id=version_id,
            title=str(meta.get("title", "")),
            abstract=str(meta.get("abstract", "")),
            sections=sections,
        )
    except Exception:  # noqa: BLE001 - profiles are best-effort
        return None


def _assert_project_owner(project_id: str, workspace_id: str, service: ProjectService) -> Project:
    project = service.repository.get_project(project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(404, "project not found")
    return project


def _project_dict(project: Project) -> dict[str, object]:
    return {
        "project_id": project.project_id,
        "workspace_id": project.workspace_id,
        "name": project.name,
        "description": project.description,
        "goal": project.goal,
        "paper_ids": project.paper_ids,
        "question_ids": project.question_ids,
        "status": project.status.value,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _question_dict(question: ResearchQuestion) -> dict[str, object]:
    return {
        "question_id": question.question_id,
        "project_id": question.project_id,
        "text": question.text,
        "detail": question.detail,
        "scope": question.scope,
        "status": question.status.value,
        "answer": question.answer,
        "evidence": question.evidence,
        "created_at": question.created_at,
    }


def _hypothesis_dict(hypothesis: Hypothesis) -> dict[str, object]:
    return {
        "hypothesis_id": hypothesis.hypothesis_id,
        "project_id": hypothesis.project_id,
        "question_id": hypothesis.question_id,
        "statement": hypothesis.statement,
        "rationale": hypothesis.rationale,
        "predictions": hypothesis.predictions,
        "status": hypothesis.status.value,
        "supporting_evidence": hypothesis.supporting_evidence,
        "created_at": hypothesis.created_at,
    }


def _run_dict(run: Any) -> dict[str, object]:
    return {
        "run_id": run.run_id,
        "project_id": run.project_id,
        "question": run.question,
        "status": run.status.value,
        "tasks": [t.model_dump(mode="json") for t in run.tasks],
        "artifact": run.artifact.model_dump(mode="json") if run.artifact else None,
        "findings": run.findings,
        "notes": run.notes,
        "created_at": run.created_at,
    }


def _comparison_dict(comparison: ComparisonSet) -> dict[str, object]:
    return {
        "comparison_id": comparison.comparison_id,
        "workspace_id": comparison.workspace_id,
        "name": comparison.name,
        "description": comparison.description,
        "question": comparison.question,
        "paper_version_ids": comparison.paper_version_ids,
        "dimensions": comparison.dimensions,
        "custom_dimensions": [
            c.model_dump(mode="json") for c in comparison.custom_dimensions
        ],
        "cells": [c.model_dump(mode="json") for c in comparison.cells],
        "synthesis": comparison.synthesis.model_dump(mode="json"),
        "status": comparison.status.value,
        "created_at": comparison.created_at,
        "updated_at": comparison.updated_at,
    }
