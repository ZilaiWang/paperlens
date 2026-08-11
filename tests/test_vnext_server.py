"""Server vNext API 测试（改进方案2 Phase A / G / H / I）。

验证 workspace 身份、项目、研究运行、对比集、术语库端点的真实可用性。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))


from fastapi.testclient import TestClient

from server.app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_vnext_store(tmp_path, monkeypatch):
    """Use a disposable database; tests must never erase `.paperlens` data."""
    import server.app.main as main
    from server.app.repositories import VNextRepository
    from server.app.services.research import ResearchService

    temporary = VNextRepository(tmp_path / "vnext.db")
    # The repository may have a developer .env pointing at a live local model.
    # Contract tests are offline and must never inherit or contact that service.
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setattr(main, "vnext_repository", temporary)
    monkeypatch.setattr(main, "research_service", ResearchService(main.repository, temporary))
    client.cookies.clear()
    created = client.post("/api/v2/workspaces/anonymous", json={})
    assert created.status_code == 200
    yield
    temporary._conn.close()
    client.cookies.clear()


class TestWorkspace:
    def test_anonymous_workspace_created(self) -> None:
        isolated = TestClient(app)
        response = isolated.post("/api/v2/workspaces/anonymous", json={"name": "Guest A"})
        assert response.status_code == 200
        data = response.json()
        assert data["workspace_id"].startswith("ws-")
        assert "paperlens_session" in isolated.cookies
        assert "session_secret" not in data

    def test_workspace_me_returns_workspace(self) -> None:
        response = client.get("/api/v2/workspaces/me")
        assert response.status_code == 200
        assert response.json()["workspace_id"].startswith("ws-")

    def test_cross_workspace_isolation(self) -> None:
        first = TestClient(app)
        second = TestClient(app)
        first.post("/api/v2/workspaces/anonymous", json={})
        second.post("/api/v2/workspaces/anonymous", json={})
        create = first.post("/api/v2/projects", json={"name": "Secret project"})
        project_id = create.json()["project_id"]
        read = second.get(f"/api/v2/projects/{project_id}")
        assert read.status_code == 404

    def test_workspace_header_cannot_impersonate(self) -> None:
        response = client.get(
            "/api/v2/workspaces/me",
            headers={"X-Workspace-Id": "ws-attacker-chosen"},
        )
        assert response.json()["workspace_id"] != "ws-attacker-chosen"


class TestProjects:
    def _create_project(self, name: str = "Survey") -> str:
        response = client.post(
            "/api/v2/projects",
            json={"name": name, "goal": "Compare detectors."},
            headers={"X-Workspace-Id": "ws-proj"},
        )
        assert response.status_code == 200
        return response.json()["project_id"]

    def test_project_crud(self) -> None:
        project_id = self._create_project("Detector survey")
        # list
        listing = client.get("/api/v2/projects", headers={"X-Workspace-Id": "ws-proj"})
        assert any(p["project_id"] == project_id for p in listing.json())
        # patch
        patched = client.patch(
            f"/api/v2/projects/{project_id}",
            json={"description": "updated"},
            headers={"X-Workspace-Id": "ws-proj"},
        )
        assert patched.json()["description"] == "updated"
        # delete
        deleted = client.delete(
            f"/api/v2/projects/{project_id}",
            headers={"X-Workspace-Id": "ws-proj"},
        )
        assert deleted.status_code == 200
        gone = client.get(f"/api/v2/projects/{project_id}", headers={"X-Workspace-Id": "ws-proj"})
        assert gone.status_code == 404

    def test_question_and_hypothesis_flow(self) -> None:
        project_id = self._create_project("Research")
        question = client.post(
            f"/api/v2/projects/{project_id}/questions",
            json={"text": "Which backbone wins?", "detail": ""},
            headers={"X-Workspace-Id": "ws-proj"},
        )
        assert question.status_code == 200
        question_id = question.json()["question_id"]
        hypothesis = client.post(
            f"/api/v2/projects/{project_id}/hypotheses",
            json={"question_id": question_id, "statement": "ResNet wins.", "rationale": ""},
            headers={"X-Workspace-Id": "ws-proj"},
        )
        assert hypothesis.status_code == 200
        assert hypothesis.json()["status"] == "PROPOSED"
        questions = client.get(
            f"/api/v2/projects/{project_id}/questions",
            headers={"X-Workspace-Id": "ws-proj"},
        )
        assert len(questions.json()) == 1

    def test_add_paper_uses_validated_json_body(self) -> None:
        project_id = self._create_project("Paper collection")
        response = client.post(
            f"/api/v2/projects/{project_id}/papers",
            json={"paper_id": "ver-test-1"},
        )
        assert response.status_code == 200
        assert response.json()["paper_ids"] == ["ver-test-1"]


class TestResearchRuns:
    def test_run_create_execute_and_list(self) -> None:
        project_response = client.post(
            "/api/v2/projects",
            json={"name": "Run project", "goal": ""},
            headers={"X-Workspace-Id": "ws-runs"},
        )
        project_id = project_response.json()["project_id"]
        created = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={"question": "Compare methods.", "paper_version_ids": []},
            headers={"X-Workspace-Id": "ws-runs"},
        )
        assert created.status_code == 200
        run_id = created.json()["run_id"]
        assert created.json()["status"] == "PLANNED"

        executed = client.post(
            f"/api/v2/projects/{project_id}/runs/{run_id}/execute",
            headers={"X-Workspace-Id": "ws-runs"},
        )
        assert executed.status_code == 200
        data = executed.json()
        assert data["status"] in ("COMPLETED", "FAILED")
        assert data["ok_count"] >= 1  # synthesize/produce tasks always ok
        assert data["artifact"] is not None
        assert data["findings"]
        assert data["findings"][0] in data["artifact"]["content"]

        listing = client.get(
            f"/api/v2/projects/{project_id}/runs",
            headers={"X-Workspace-Id": "ws-runs"},
        )
        assert len(listing.json()) == 1


class TestComparisonSets:
    def test_comparison_set_lifecycle(self) -> None:
        created = client.post(
            "/api/v2/comparison-sets",
            json={
                "name": "Detector comparison",
                "question": "Which is best?",
                "paper_version_ids": ["v1", "v2"],
            },
            headers={"X-Workspace-Id": "ws-cmp"},
        )
        assert created.status_code == 200
        comparison_id = created.json()["comparison_id"]
        assert created.json()["status"] == "DRAFT"

        # align (no profiles stored -> empty matrix but 200)
        aligned = client.post(
            f"/api/v2/comparison-sets/{comparison_id}/align",
            headers={"X-Workspace-Id": "ws-cmp"},
        )
        assert aligned.status_code == 200
        assert "matrix" in aligned.json()

        synthesized = client.post(
            f"/api/v2/comparison-sets/{comparison_id}/synthesize",
            headers={"X-Workspace-Id": "ws-cmp"},
        )
        assert synthesized.status_code == 200
        assert synthesized.json()["status"] == "SYNTHESIZED"

        listing = client.get(
            "/api/v2/comparison-sets",
            headers={"X-Workspace-Id": "ws-cmp"},
        )
        assert len(listing.json()) == 1

    def test_comparison_set_workspace_isolated(self) -> None:
        first = TestClient(app)
        second = TestClient(app)
        first.post("/api/v2/workspaces/anonymous", json={})
        second.post("/api/v2/workspaces/anonymous", json={})
        created = first.post(
            "/api/v2/comparison-sets",
            json={"name": "Isolated", "paper_version_ids": ["v1"]},
        )
        comparison_id = created.json()["comparison_id"]
        other = second.get(f"/api/v2/comparison-sets/{comparison_id}")
        assert other.status_code == 404

    def test_comparison_set_with_custom_dimensions(self) -> None:
        created = client.post(
            "/api/v2/comparison-sets",
            json={
                "name": "Custom dims",
                "paper_version_ids": ["v1"],
                "dimensions": ["problem"],
                "custom_dimensions": [
                    {"name": "参数量", "instruction": "提取参数量（M）"},
                ],
            },
            headers={"X-Workspace-Id": "ws-custom"},
        )
        assert created.status_code == 200
        data = created.json()
        assert data["dimensions"] == ["problem"]
        assert data["custom_dimensions"][0]["name"] == "参数量"


class TestTermbaseAPI:
    def test_term_upsert_and_list(self) -> None:
        upsert = client.post(
            "/api/v2/termbase",
            json={
                "source": "backbone",
                "target": "骨干网络",
                "scope": "PROJECT",
                "policy": "TRANSLATE",
            },
            headers={"X-Workspace-Id": "ws-term"},
        )
        assert upsert.status_code == 200
        listing = client.get("/api/v2/termbase")
        assert any(t["source"] == "backbone" for t in listing.json())

    def test_term_delete(self) -> None:
        client.post(
            "/api/v2/termbase",
            json={"source": "temp-term", "target": "临时", "scope": "PROJECT"},
            headers={"X-Workspace-Id": "ws-term"},
        )
        deleted = client.delete(
            "/api/v2/termbase/PROJECT/temp-term",
            headers={"X-Workspace-Id": "ws-term"},
        )
        assert deleted.status_code == 200

    def test_terms_are_workspace_isolated(self) -> None:
        first = TestClient(app)
        second = TestClient(app)
        first.post("/api/v2/workspaces/anonymous", json={})
        second.post("/api/v2/workspaces/anonymous", json={})
        created = first.post(
            "/api/v2/termbase",
            json={"source": "private-term", "target": "私有", "scope": "PROJECT"},
        )
        assert created.status_code == 200
        sources = {entry["source"] for entry in second.get("/api/v2/termbase").json()}
        assert "private-term" not in sources

    def test_system_terms_are_read_only(self) -> None:
        response = client.post(
            "/api/v2/termbase",
            json={"source": "global-overwrite", "target": "x", "scope": "SYSTEM"},
        )
        assert response.status_code == 403


class TestContextPack:
    def test_context_pack_built(self) -> None:
        project_response = client.post(
            "/api/v2/projects",
            json={"name": "Pack project", "goal": "Goal"},
            headers={"X-Workspace-Id": "ws-pack"},
        )
        project_id = project_response.json()["project_id"]
        pack = client.post(
            f"/api/v2/projects/{project_id}/context-pack",
            headers={"X-Workspace-Id": "ws-pack"},
        )
        assert pack.status_code == 200
        data = pack.json()
        assert data["project_id"] == project_id
        assert "questions" in data


class TestTranslationV2API:
    def test_translate_v2_endpoint_shape(self) -> None:
        """端点结构稳定：无论有无 LLM key 都返回翻译数组与阶段信息。"""
        response = client.post(
            "/api/v2/translations/v2",
            json={
                "paragraphs": ["We freeze the backbone [12]."],
                "section_title": "Method",
            },
            headers={"X-Workspace-Id": "ws-trans"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "translations" in data
        assert len(data["translations"]) == 1
        assert "stages_run" in data
        assert data["model_available"] is False

    def test_scan_terms_returns_known_terms(self) -> None:
        # 先写入系统术语 backbone
        from server.app.main import vnext_repository

        workspace_id = client.get("/api/v2/workspaces/me").json()["workspace_id"]
        vnext_repository.save_term_entry(
            workspace_id,
            {
                "scope": "SYSTEM",
                "source": "backbone",
                "target": "骨干网络",
                "policy": "TRANSLATE",
                "locked": False,
                "keep_english": False,
                "confidence": 0.98,
                "updated_at": "2026-08-11T00:00:00Z",
            }
        )
        response = client.post(
            "/api/v2/translations/scan-terms",
            json={"text": "The backbone network is fast."},
            headers={"X-Workspace-Id": "ws-trans"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 1
        assert any(t["source"] == "backbone" for t in data["terms"])
