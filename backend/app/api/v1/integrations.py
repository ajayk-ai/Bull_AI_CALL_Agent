import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status

from app.api.deps import ContextDep, SessionDep, require
from app.models.org import User
from app.rbac.permissions import Permission
from app.schemas.imports import ImportUploadOut
from app.schemas.integrations import ConnectionIn, ConnectionOut, ConnectionTestResult, FetchRequest
from app.services import integrations

router = APIRouter(prefix="/integrations", tags=["connected apps"])

Manage = Annotated[User, Depends(require(Permission.INTEGRATIONS_MANAGE))]


@router.get("", response_model=list[ConnectionOut])
async def list_connections(user: Manage, session: SessionDep):
    return await integrations.list_connections(session, user)


@router.post("", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
async def create_connection(body: ConnectionIn, user: Manage, session: SessionDep, ctx: ContextDep):
    return await integrations.create(session, user, body, ctx)


@router.get("/sample-result")
async def sample_result(user: Manage) -> dict[str, Any]:
    """The JSON a "send results" connection receives after each call (event "call.completed")."""
    return integrations.sample_payload()


@router.get("/{connection_id}", response_model=ConnectionOut)
async def get_connection(connection_id: uuid.UUID, user: Manage, session: SessionDep):
    return await integrations.get_connection(session, user, connection_id)


@router.put("/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    connection_id: uuid.UUID, body: ConnectionIn, user: Manage, session: SessionDep, ctx: ContextDep
):
    """Replaces the settings. `secret` / `signing_secret`: omit or null to keep, "" to remove."""
    return await integrations.update(session, user, connection_id, body, ctx)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(connection_id: uuid.UUID, user: Manage, session: SessionDep, ctx: ContextDep) -> None:
    await integrations.delete(session, user, connection_id, ctx)


@router.post("/{connection_id}/test", response_model=ConnectionTestResult)
async def test_connection(connection_id: uuid.UUID, user: Manage, session: SessionDep):
    """fetch_contacts: reads the list and shows what it found. send_results: delivers a sample result."""
    return await integrations.test(session, user, connection_id)


@router.post("/{connection_id}/fetch", response_model=ImportUploadOut, status_code=status.HTTP_201_CREATED)
async def fetch_contacts(
    connection_id: uuid.UUID,
    body: FetchRequest,
    user: Annotated[User, Depends(require(Permission.IMPORTS_WRITE))],
    session: SessionDep,
    ctx: ContextDep,
):
    """Brings the list in as an upload; continue with POST /imports/{id}/process, as for a file."""
    return await integrations.fetch(session, user, connection_id, body, ctx)
