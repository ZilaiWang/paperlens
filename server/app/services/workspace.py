"""Workspace service: create/claim anonymous workspaces (改进方案2 §51-52)."""

from __future__ import annotations

from paperlens_core.ir.identity import Workspace, WorkspaceClaim, WorkspaceKind

from ..repositories import VNextRepository
from ..repository import now_iso


class WorkspaceService:
    def __init__(self, repository: VNextRepository):
        self.repository = repository

    def create_anonymous(self, *, name: str = "") -> Workspace:
        workspace = Workspace.anonymous(name=name, created_at=now_iso())
        self.repository.save_workspace(workspace.model_dump(mode="json"))
        return workspace

    def get(self, workspace_id: str) -> Workspace | None:
        data = self.repository.get_workspace(workspace_id)
        if data is None:
            return None
        return Workspace(**data)

    def claim(self, workspace_id: str, user_id: str) -> WorkspaceClaim:
        workspace = self.get(workspace_id)
        if workspace is None:
            raise ValueError("workspace not found")
        claim = WorkspaceClaim(
            workspace_id=workspace_id,
            user_id=user_id,
            created_at=now_iso(),
        )
        # bind the workspace to a real account
        self.repository.save_workspace(
            {
                **workspace.model_dump(mode="json"),
                "owner_user_id": user_id,
                "kind": WorkspaceKind.PERSONAL.value,
            }
        )
        return claim
