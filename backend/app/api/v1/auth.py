from fastapi import APIRouter

from app.api.deps import ContextDep, CurrentUser, SessionDep
from app.core.redis import get_redis
from app.rbac.permissions import ROLE_PERMISSIONS
from app.schemas.org import ChangePasswordRequest, LoginRequest, MeOut, RefreshRequest, TokenResponse
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: SessionDep, ctx: ContextDep) -> TokenResponse:
    return await auth.login(session, get_redis(), body.email, body.password, ctx)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, session: SessionDep) -> TokenResponse:
    return await auth.refresh(session, body.refresh_token)


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser) -> MeOut:
    return MeOut(
        **{f: getattr(user, f) for f in MeOut.model_fields if f != "permissions"},
        permissions=sorted(ROLE_PERMISSIONS[user.role]),
    )


@router.post("/change-password", response_model=TokenResponse)
async def change_password(
    body: ChangePasswordRequest, user: CurrentUser, session: SessionDep, ctx: ContextDep
) -> TokenResponse:
    return await auth.change_password(session, user, body.current_password, body.new_password, ctx)
