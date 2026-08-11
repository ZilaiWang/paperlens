"""Anonymous-first workspace authentication.

Workspace identifiers are ownership labels, not credentials. A request is
accepted only when its opaque session token resolves to a stored workspace.
Browser sessions use an HttpOnly cookie; API clients may use a Bearer token.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Request, Response

SESSION_COOKIE = "paperlens_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30


def session_token_from_request(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    legacy = request.headers.get("X-Session-Token", "").strip()
    if legacy:
        return legacy
    return request.cookies.get(SESSION_COOKIE, "").strip()


def resolve_workspace_id(request: Request, repository: object) -> str:
    """Resolve a workspace from a server-issued session token.

    ``X-Workspace-Id`` is deliberately ignored: allowing the client to choose
    an ownership label makes every workspace guessable and defeats isolation.
    """
    token = session_token_from_request(request)
    if not token:
        raise HTTPException(401, "workspace session required")
    workspace = repository.get_workspace_by_session_token(token)
    if workspace is None:
        raise HTTPException(401, "invalid workspace session")
    return str(workspace["workspace_id"])


def set_session_cookie(response: Response, token: str) -> None:
    secure = os.environ.get("PAPERLENS_SECURE_COOKIES", "").lower() in {
        "1",
        "true",
        "yes",
    }
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
