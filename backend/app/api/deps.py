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
from app.rbac.permissions import Permission, has_permission

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_bearer = HTTPBearer(auto_error=False)


# Reachable while the user still has to replace a password the admin set.
_ALLOWED_BEFORE_PASSWORD_CHANGE = {"/api/v1/auth/me", "/api/v1/auth/change-password"}


class PasswordChangeRequired(Forbidden):
    code = "password_change_required"


async def get_current_user(
    request: Request,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise Unauthorized("Not authenticated")
    payload = decode_token(credentials.credentials, "access")
    user = await session.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active or user.token_version != payload["ver"]:
        raise Unauthorized("Session is no longer valid")
    if user.must_change_password and route_path(request.scope) not in _ALLOWED_BEFORE_PASSWORD_CHANGE:
        raise PasswordChangeRequired("Choose a new password before continuing")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require(permission: Permission) -> Callable:
    async def _check(user: CurrentUser) -> User:
        if not has_permission(user, permission):
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
