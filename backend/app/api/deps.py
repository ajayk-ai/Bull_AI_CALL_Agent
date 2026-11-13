"""FastAPI dependencies: database session, current user, permission checks, request context."""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.errors import Forbidden, Unauthorized
from app.core.logging import request_id_var
from app.core.paths import route_path
from app.core.security import decode_token
from app.db.session import get_session
from app.models.org import User
from app.rbac.permissions import API_KEY_ACCESS, Permission, has_permission
from app.services import api_keys

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_bearer = HTTPBearer(auto_error=False)


# Reachable while the user still has to replace a password the admin set.
_ALLOWED_BEFORE_PASSWORD_CHANGE = {"/api/v1/auth/me", "/api/v1/auth/change-password"}


class PasswordChangeRequired(Forbidden):
    code = "password_change_required"


# The only routes an API key can reach: the calling work and MCP. Accounts, keys, connected apps, departments and
# the audit log always need a person signed in.
_API_KEY_ROUTES = (
    "/api/v1/campaigns",
    "/api/v1/calls",
    "/api/v1/scripts",
    "/api/v1/script-versions",
    "/api/v1/contacts",
    "/api/v1/imports",
    "/api/v1/mcp",
)


def _api_key_route(path: str) -> bool:
    return any(path == route or path.startswith(route + "/") for route in _API_KEY_ROUTES)


async def get_current_user(
    request: Request,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    token = credentials.credentials if credentials else request.headers.get("x-api-key")
    if not token:
        raise Unauthorized("Not authenticated")
    if api_keys.looks_like_key(token):
        if not _api_key_route(route_path(request.scope)):
            raise Forbidden("API keys cannot use this endpoint; sign in as a person instead")
        key, user = await api_keys.authenticate(session, token)
        request.state.api_key = key
        return user
    payload = decode_token(token, "access")
    user = await session.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active or user.token_version != payload["ver"]:
        raise Unauthorized("Session is no longer valid")
    if user.must_change_password and route_path(request.scope) not in _ALLOWED_BEFORE_PASSWORD_CHANGE:
        raise PasswordChangeRequired("Choose a new password before continuing")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def allowed(request: Request, user: User, permission: Permission) -> bool:
    """The user's role allows it and, for an API key, so does the key's access level."""
    key = getattr(request.state, "api_key", None)
    return has_permission(user, permission) and (key is None or permission in API_KEY_ACCESS[key.access])


def require(permission: Permission) -> Callable:
    async def _check(request: Request, user: CurrentUser) -> User:
        if not allowed(request, user, permission):
            key = getattr(request.state, "api_key", None)
            if key is not None:
                raise Forbidden(f"This API key's access does not include {permission}")
            raise Forbidden(f"Missing permission: {permission}")
        return user

    return _check


def get_request_context(request: Request) -> RequestContext:
    return RequestContext(
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:300] or None,
        request_id=request_id_var.get(),
    )


ContextDep = Annotated[RequestContext, Depends(get_request_context)]
