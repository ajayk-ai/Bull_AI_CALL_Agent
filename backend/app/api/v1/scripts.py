import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import ContextDep, SessionDep, require
from app.models.org import User
from app.rbac.permissions import Permission
from app.schemas.scripts import (
    ReviewDecision,
    ScriptCreate,
    ScriptOut,
    ScriptUpdate,
    ScriptVersionBody,
    ScriptVersionOut,
)
from app.services import scripts

router = APIRouter(tags=["scripts"])

ReadScripts = Annotated[User, Depends(require(Permission.SCRIPTS_READ))]
WriteScripts = Annotated[User, Depends(require(Permission.SCRIPTS_WRITE))]
ApproveScripts = Annotated[User, Depends(require(Permission.SCRIPTS_APPROVE))]


@router.get("/scripts", response_model=list[ScriptOut])
async def list_scripts(
    user: ReadScripts, session: SessionDep, include_archived: bool = False, department_id: uuid.UUID | None = None
):
    return await scripts.list_scripts(session, user, include_archived, department_id)


@router.post("/scripts", response_model=ScriptOut, status_code=status.HTTP_201_CREATED)
async def create_script(body: ScriptCreate, user: WriteScripts, session: SessionDep, ctx: ContextDep):
    """Creates the script and its first version, as a draft."""
    return await scripts.create_script(session, user, body, ctx)


@router.get("/scripts/{script_id}", response_model=ScriptOut)
async def get_script(script_id: uuid.UUID, user: ReadScripts, session: SessionDep):
    return await scripts.get_script(session, user, script_id)


@router.patch("/scripts/{script_id}", response_model=ScriptOut)
async def update_script(
    script_id: uuid.UUID, body: ScriptUpdate, user: WriteScripts, session: SessionDep, ctx: ContextDep
):
    return await scripts.update_script(session, user, script_id, body, ctx)


@router.post("/scripts/{script_id}/versions", response_model=ScriptVersionOut, status_code=status.HTTP_201_CREATED)
async def create_version(
    script_id: uuid.UUID, body: ScriptVersionBody, user: WriteScripts, session: SessionDep, ctx: ContextDep
):
    return await scripts.create_version(session, user, script_id, body, ctx)


@router.get("/script-versions/{version_id}", response_model=ScriptVersionOut)
async def get_version(version_id: uuid.UUID, user: ReadScripts, session: SessionDep):
    version, _ = await scripts.get_version(session, user, version_id)
    return version


@router.put("/script-versions/{version_id}", response_model=ScriptVersionOut)
async def update_version(
    version_id: uuid.UUID, body: ScriptVersionBody, user: WriteScripts, session: SessionDep, ctx: ContextDep
):
    """Replaces a draft's configuration. Published versions cannot be changed; create a new version instead."""
    return await scripts.update_version(session, user, version_id, body, ctx)


@router.post("/script-versions/{version_id}/submit", response_model=ScriptVersionOut)
async def submit_version(version_id: uuid.UUID, user: WriteScripts, session: SessionDep, ctx: ContextDep):
    return await scripts.submit_version(session, user, version_id, ctx)


@router.post("/script-versions/{version_id}/approve", response_model=ScriptVersionOut)
async def approve_version(
    version_id: uuid.UUID, body: ReviewDecision, user: ApproveScripts, session: SessionDep, ctx: ContextDep
):
    """Publishes the version. The previously published version is retired; campaigns using it keep it."""
    return await scripts.approve_version(session, user, version_id, body.comments, ctx)


@router.post("/script-versions/{version_id}/reject", response_model=ScriptVersionOut)
async def reject_version(
    version_id: uuid.UUID, body: ReviewDecision, user: ApproveScripts, session: SessionDep, ctx: ContextDep
):
    return await scripts.reject_version(session, user, version_id, body.comments, ctx)
