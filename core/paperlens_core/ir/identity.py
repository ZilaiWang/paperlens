"""Workspace identity model (Anonymous-first, 改进方案1 §十七-十九 / 改进方案2 §51-53).

V1 used a pseudo-user ``X-User-Id`` header which is quota-only, never auth.
vNext introduces:

    User (auth identity, optional for anonymous users)
      └── Workspace (owner of every resource: papers, projects, termbase, runs)

A user may have multiple workspaces (personal / lab / shared).  Every
repository query is scoped by ``workspace_id`` so id-guessing across
workspaces is impossible even without a full login system.

Anonymous-first flow (改进方案2 §51):

    POST /identity/anonymous
        → workspace_id (random 128-bit) + session_secret
        → HttpOnly Secure cookie
        → user claims it later via "save your workspace"
"""

from __future__ import annotations

import secrets
import uuid
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class UserProvider(str, Enum):
    ANONYMOUS = "ANONYMOUS"
    GITHUB = "GITHUB"
    EMAIL_LINK = "EMAIL_LINK"
    LOCAL = "LOCAL"  # self-host admin


class WorkspaceKind(str, Enum):
    PERSONAL = "PERSONAL"
    LAB = "LAB"
    SHARED = "SHARED"


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


class UserAccount(BaseModel):
    """A real (claimable) account; anonymous sessions have no UserAccount."""

    model_config = ConfigDict(extra="allow")

    user_id: str
    provider: UserProvider = UserProvider.ANONYMOUS
    email: str = ""
    display_name: str = ""
    created_at: str = ""
    # provider-specific: github login / magic-link address etc.
    provider_uid: str = ""


class Workspace(BaseModel):
    """The ownership boundary for all resources."""

    model_config = ConfigDict(extra="allow")

    workspace_id: str
    owner_user_id: str = ""  # empty => anonymous session workspace
    kind: WorkspaceKind = WorkspaceKind.PERSONAL
    name: str = ""
    session_secret: str = ""  # bearer for anonymous sessions
    created_at: str = ""

    @classmethod
    def anonymous(cls, *, name: str = "", created_at: str = "") -> "Workspace":
        return cls(
            workspace_id=f"ws-{secrets.token_hex(16)}",
            kind=WorkspaceKind.PERSONAL,
            name=name or "Guest workspace",
            session_secret=secrets.token_hex(32),
            created_at=created_at,
        )


class WorkspaceClaim(BaseModel):
    """Binds an anonymous workspace to a permanent user account (改进方案2 §52)."""

    model_config = ConfigDict(extra="allow")

    claim_id: str = Field(default_factory=lambda: new_id("claim"))
    workspace_id: str
    user_id: str
    created_at: str = ""


def is_owned(workspace_id: str, resource_workspace_id: str) -> bool:
    """Defense-in-depth helper: reject cross-workspace resource access."""
    return bool(workspace_id) and workspace_id == resource_workspace_id
