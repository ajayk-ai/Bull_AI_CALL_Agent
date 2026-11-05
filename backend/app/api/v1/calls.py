import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import ContextDep, SessionDep, require
from app.core.config import get_settings
from app.models.enums import CallStatus
from app.models.org import User
from app.rbac.permissions import Permission
from app.schemas.calls import CallCreate, CallDetail, CallOut
from app.schemas.common import Page, PageParams
from app.services import calls
from app.voice.deps import EngineDep, TelephonyDep

router = APIRouter(prefix="/calls", tags=["calls"])

ReadCalls = Annotated[User, Depends(require(Permission.CALLS_READ))]
PlaceCalls = Annotated[User, Depends(require(Permission.CALLS_PLACE))]


@router.get("/mode")
async def calling_mode(user: ReadCalls) -> dict:
    """Whether this server places real calls ("live"), simulated ones ("mock"), or none ("disabled")."""
    return {"mode": get_settings().telephony_mode}


@router.post("", response_model=CallOut, status_code=status.HTTP_201_CREATED)
async def place_call(
    body: CallCreate, user: PlaceCalls, session: SessionDep, ctx: ContextDep, telephony: TelephonyDep, engine: EngineDep
):
    """Places one outbound call now. Checks do-not-call, calling hours, the concurrency limit and that the number
    is not already being called."""
    return await calls.place_call(session, user, body, telephony, engine, ctx)


@router.get("", response_model=Page[CallOut])
async def list_calls(
    user: ReadCalls,
    session: SessionDep,
    params: Annotated[PageParams, Query()],
    status: CallStatus | None = None,
    contact_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
):
    items, total = await calls.list_calls(session, user, params, status, contact_id, campaign_id)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.get("/{call_id}", response_model=CallDetail)
async def get_call(call_id: uuid.UUID, user: ReadCalls, session: SessionDep):
    return await calls.get_call(session, user, call_id)


@router.post("/{call_id}/hang-up", response_model=CallOut)
async def hang_up(call_id: uuid.UUID, user: PlaceCalls, session: SessionDep, ctx: ContextDep, telephony: TelephonyDep):
    return await calls.hang_up(session, user, call_id, telephony, ctx)
