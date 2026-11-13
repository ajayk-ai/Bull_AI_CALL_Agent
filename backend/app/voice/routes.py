"""Endpoints the telephony provider calls. No user login: every URL carries a signed, per-call token.

POST /telephony/{provider}/flow     the call was answered; we answer with where to stream the audio
POST /telephony/{provider}/status   status changes (ringing, completed, recording ready, ...)
WS   /telephony/{provider}/media    the call's audio
"""

import asyncio
import logging
import time

from fastapi import APIRouter, Query, Request, WebSocket
from fastapi.responses import JSONResponse

from app.db.session import get_sessionmaker
from app.providers.telephony.frejun import FreJunMediaStream
from app.services import calls, extraction, integrations
from app.voice import tokens
from app.voice.deps import EngineDep, TelephonyDep
from app.voice.session import CallSession

log = logging.getLogger(__name__)
router = APIRouter(prefix="/telephony/{provider}", tags=["telephony webhooks"], include_in_schema=False)

WS_POLICY_VIOLATION = 1008
_REFUSED = JSONResponse({"error": {"code": "forbidden", "message": "Invalid or expired call token"}}, 403)


@router.post("/flow")
async def flow(provider: str, t: str | None = Query(None)):
    call_id = tokens.check(t, "flow")
    if call_id is None:
        return _REFUSED
    async with get_sessionmaker()() as session:
        call = await calls.get_for_provider(session, call_id, provider)
        if call is None:
            return _REFUSED
        return await calls.flow(session, call)


@router.post("/status")
async def status(provider: str, request: Request, t: str | None = Query(None)):
    call_id = tokens.check(t, "status")
    if call_id is None:
        return _REFUSED
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {"body": payload}
    except ValueError:
        payload = {"body": (await request.body())[:2000].decode(errors="replace")}
    async with get_sessionmaker()() as session:
        call = await calls.get_for_provider(session, call_id, provider)
        if call is None:
            return _REFUSED
        await calls.status_event(session, call, payload)
    return {"ok": True}


@router.websocket("/media")
async def media(
    websocket: WebSocket, provider: str, telephony: TelephonyDep, engine: EngineDep, t: str | None = Query(None)
):
    call_id = tokens.check(t, "media")
    if call_id is None:
        await websocket.close(code=WS_POLICY_VIOLATION)
        return
    # Short database work only: the session is closed before the call's audio starts.
    async with get_sessionmaker()() as session:
        call = await calls.get_for_provider(session, call_id, provider)
        if call is None or not await calls.claim_media(session, call):
            log.warning("Media stream refused for call %s", call_id)
            await websocket.close(code=WS_POLICY_VIOLATION)
            return
        econfig, limits, scenario = await calls.session_setup(session, call)
        provider_call_id = call.provider_call_id

    await websocket.accept()
    log.info("Call %s connected", call_id)
    stream = FreJunMediaStream(websocket)
    guard = calls.make_guard(limits, time.monotonic())
    result = await CallSession(stream, engine, econfig, guard, scenario=scenario).run()
    # Saving the call must not depend on the connection: run it as its own task, shielded from cancellation
    # of this handler, and waited for at shutdown (see pending_post_call_work).
    task = asyncio.create_task(_after_call(call_id, provider_call_id, result, telephony))
    _post_call_tasks.add(task)
    task.add_done_callback(_post_call_tasks.discard)
    await asyncio.shield(task)


_post_call_tasks: set[asyncio.Task] = set()


async def _after_call(call_id, provider_call_id: str | None, result, telephony) -> None:
    if result.we_hung_up and provider_call_id:
        await telephony.hangup(provider_call_id)
    async with get_sessionmaker()() as session:
        await calls.finish(session, call_id, result)
    log.info("Call %s ended: %s, outcome %s, %d turns", call_id, result.end_reason, result.outcome, len(result.turns))
    # The structured result (LangChain + Gemini). Its failure never affects the stored call.
    try:
        async with get_sessionmaker()() as session:
            await extraction.extract(session, call_id)
    except Exception:
        log.exception("Extraction for call %s failed", call_id)
    # Then hand the result to the department's connected apps. Their failures never affect the call either.
    try:
        await integrations.deliver_call_results(call_id)
    except Exception:
        log.exception("Sending call %s to connected apps failed", call_id)


async def pending_post_call_work() -> None:
    """Called at shutdown: lets calls that just ended finish saving."""
    if _post_call_tasks:
        await asyncio.gather(*_post_call_tasks, return_exceptions=True)
