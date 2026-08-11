"""Regression tests for public API request contracts and adapters."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from paperlens_core.comparison import ComparisonCell, CrossPaperAnswer
from paperlens_core.documents import Paper, PaperVersion
from paperlens_core.llm import StaticJSONModel
from paperlens_core.models import CoverageStatus
from pydantic import ValidationError

from server.app.main import app
from server.app.schemas import ComparisonRequest
from server.app.services.comparisons import ARTIFACT_FIELD_MAP, translate_comparison_cells


def test_cross_paper_answer_rejects_empty_claim() -> None:
    with pytest.raises(ValidationError):
        CrossPaperAnswer(claim="", comparability_status="NOT_COMPARABLE")


def test_comparison_endpoint_declares_json_request_body() -> None:
    operation = app.openapi()["paths"]["/api/v1/comparisons"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/ComparisonRequest")


def test_comparison_request_accepts_only_two_or_three_versions() -> None:
    assert ComparisonRequest(paper_version_ids=["v1", "v2"]).paper_version_ids == ["v1", "v2"]
    with pytest.raises(ValidationError):
        ComparisonRequest(paper_version_ids=["v1"])
    with pytest.raises(ValidationError):
        ComparisonRequest(paper_version_ids=["v1", "v2", "v3", "v4"])


def test_comparison_artifact_mapping_uses_profile_schema_fields() -> None:
    assert ARTIFACT_FIELD_MAP["task_definition"] == "task"
    assert ARTIFACT_FIELD_MAP["code_and_data"] == "reproducibility"


def test_comparison_cell_translation_uses_stable_keys() -> None:
    model = StaticJSONModel(
        [{"translations": {"version-1|method_core": "一种证据约束方法"}}]
    )
    cells = [
        ComparisonCell(
            paper_id="version-1",
            field="method_core",
            value="An evidence-constrained method",
            status=CoverageStatus.FOUND,
            evidence_ids=["ev-1"],
        )
    ]
    assert translate_comparison_cells(model, cells) == {
        "version-1|method_core": "一种证据约束方法"
    }


def test_versions_endpoint_returns_serializable_rows(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the reader bootstrap contract from regressing to row attributes."""
    from server.app.repository import Repository

    repo = Repository(tmp_path / "versions.db")
    monkeypatch.setattr("server.app.main.repository", repo)
    repo.create_paper(
        Paper(
            paper_id="paper-1",
            canonical_title="A paper",
            created_at="2026-08-11T00:00:00Z",
        )
    )
    repo.create_version(
        PaperVersion(
            version_id="version-1",
            paper_id="paper-1",
            version_label="v1",
            source="UPLOAD",
            file_name="paper.pdf",
            file_sha256="sha",
            page_count=3,
            created_at="2026-08-11T00:00:00Z",
        )
    )

    response = TestClient(app).get("/api/papers/paper-1/versions")

    assert response.status_code == 200
    assert response.json() == [
        {
            "version_id": "version-1",
            "paper_id": "paper-1",
            "version_label": "v1",
            "source": "UPLOAD",
            "file_name": "paper.pdf",
            "file_sha256": "sha",
            "file_path": "",
            "page_count": 3,
            "parse_status": "READY",
            "created_at": "2026-08-11T00:00:00Z",
        }
    ]
