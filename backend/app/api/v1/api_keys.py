import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import ContextDep, SessionDep, require
from app.models.org import User
from app.rbac.permissions import Permission
from app.schemas.api_keys import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from app.services import api_keys

router = APIRouter(prefix="/api-keys", tags=["api keys"])

Manage = Annotated[User, Depends(require(Permission.API_KEYS_MANAGE))]


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(user: Manage, session: SessionDep):
    """Your keys (admins: every key). Keys themselves are never shown again after creation."""
    return await api_keys.list_keys(session, user)


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_key(body: ApiKeyCreate, user: Manage, session: SessionDep, ctx: ContextDep):
    """Creates a key that acts as you, limited to `access`. The response holds the key; copy it now."""
    return await api_keys.create(session, user, body, ctx)


@router.post("/{key_id}/revoke", response_model=ApiKeyOut)
async def revoke_key(key_id: uuid.UUID, user: Manage, session: SessionDep, ctx: ContextDep):
    return await api_keys.revoke(session, user, key_id, ctx)
