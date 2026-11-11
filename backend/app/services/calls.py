"""Placing and tracking calls: the call controller.

Deterministic code decides everything about a call: whether it may be placed (permissions, do-not-call, calling
hours, concurrency, one call per number at a time), its status from provider events, and what is stored
afterwards. The AI agent only converses and can ask to end the call.
"""

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import phone
from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.errors import AppError, Conflict, NotFound, TooManyRequests, ValidationFailed
from app.core.redis import get_redis
from app.core.security import decrypt
from app.models.calls import Call, CallEvent, Recording, Transcript
from app.models.campaigns import Campaign, CampaignContact
from app.models.contacts import Contact, DoNotCall
from app.models.enums import CallStatus, ScriptVersionStatus
from app.models.extraction import ExtractedResult
from app.models.org import User
from app.models.scripts import Script, ScriptVersion
from app.providers.telephony import CallUrls, TelephonyError, TelephonyProvider, frejun
from app.rbac.permissions import can_see, resolve_department, visible_departments
from app.schemas.calls import CallCreate, CallDetail, CallEventOut, CallOut, ExtractionOut, RecordingOut
from app.schemas.campaigns import CallingWindow
from app.schemas.common import PageParams
from app.services import audit, windows
from app.services.contacts import is_suppressed
from app.services.scripts import context_problems
from app.voice import tokens
from app.voice.engine import EngineConfig, VoiceEngine
from app.voice.fsm import ACTIVE, TERMINAL, ConversationGuard, after_provider_end, can_move
from app.voice.prompt import TOOLS, build_instructions
from app.voice.scenario import ScenarioController
from app.voice.session import SessionResult

log = logging.getLogger(__name__)

# A call still "active" this long after it started never got a final status from the provider.
STALE_AFTER_EXTRA = timedelta(minutes=10)


class CallingUnavailable(AppError):
    status_code = 503
    code = "calling_unavailable"


def _now() -> datetime:
    return datetime.now(UTC)


def _lock_key(phone_hash: str) -> str:
    return f"call:phone:{phone_hash}"


async def _release_lock(call: Call) -> None:
    redis = get_redis()
    key = _lock_key(call.phone_hash)
    if await redis.get(key) == str(call.id):
        await redis.delete(key)


def _base_url() -> str:
    return (get_settings().public_url or "https://mock.invalid").rstrip("/")


def call_urls(call: Call) -> CallUrls:
    base = f"{_base_url()}/telephony/{call.provider}"
    return CallUrls(
        flow_url=f"{base}/flow?t={tokens.make(call.id, 'flow')}",
        status_url=f"{base}/status?t={tokens.make(call.id, 'status')}",
    )


def media_url(call: Call) -> str:
    base = _base_url().replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    return f"{base}/telephony/{call.provider}/media?t={tokens.make(call.id, 'media')}"


def engine_config(script_config: dict, system_instruction: str, language: str | None) -> EngineConfig:
    return EngineConfig(
        system_instruction=system_instruction,
        voice_name=script_config["voice"]["voice_name"],
        language=language,
        tools=TOOLS,
        silence_ms=get_settings().gemini_silence_ms,
    )


# ---- placing a call ----


async def _expire_stale_calls(session: AsyncSession) -> None:
    """Calls that never received a final status would block the concurrency limit forever."""
    cutoff = _now() - timedelta(seconds=get_settings().max_call_seconds_hard) - STALE_AFTER_EXTRA
    stale = await session.scalars(select(Call).where(Call.status.in_(ACTIVE), Call.created_at < cutoff))
    for call in stale:
        call.status = CallStatus.FAILED
        call.end_reason = "no_final_status"
        call.error = "No final status was received from the telephony provider"
        call.ended_at = call.ended_at or _now()
        await _release_lock(call)
    await session.flush()


async def place_call(
    session: AsyncSession,
    actor: User,
    data: CallCreate,
    telephony: TelephonyProvider,
    engine: VoiceEngine,
    ctx: RequestContext | None,
    at: datetime | None = None,
    campaign: Campaign | None = None,
    campaign_contact: CampaignContact | None = None,
) -> Call:
    """Places one call. Individual calls come from users; campaign calls from the dialer (app/services/dialer.py)."""
    settings = get_settings()
    at = at or _now()

    # Who is being called.
    if data.contact_id:
        contact = await session.get(Contact, data.contact_id)
        if contact is None or contact.deleted_at is not None or not can_see(actor, contact.department_id):
            raise NotFound("Contact not found")
        department_id = contact.department_id
        number = phone.normalise(decrypt(contact.phone_encrypted))
        person = {"name": contact.name, "company": contact.company}
        default_language = contact.language
    else:
        department_id = resolve_department(actor, data.department_id)
        contact = None
        try:
            number = phone.normalise(data.phone or "")
        except phone.InvalidPhoneNumber as exc:
            raise ValidationFailed(str(exc), details={"field": "phone"})
        person = {"name": data.name, "company": data.company}
        default_language = None

    # With what script.
    version = await session.get(ScriptVersion, data.script_version_id)
    script = await session.get(Script, version.script_id) if version else None
    if version is None or script is None or script.department_id != department_id:
        raise ValidationFailed("Script version not found in this department")
    if version.status != ScriptVersionStatus.PUBLISHED:
        raise ValidationFailed(f"Only published script versions can be used; this one is {version.status}")
    config = version.config
    language = data.language or (default_language if default_language in config["languages"]["allowed"] else None)
    if language and language not in config["languages"]["allowed"]:
        raise ValidationFailed(f"The script does not allow {language}")
    if problems := context_problems(config, data.context):
        raise ValidationFailed("The call is missing data the script needs", details={"problems": problems})

    # Whether it may be placed now.
    if await is_suppressed(session, number.hash, department_id):
        raise Conflict("This number is on the do-not-call list")
    window = CallingWindow.model_validate(campaign.calling_window or {}) if campaign else CallingWindow()
    if (campaign or settings.individual_call_window_enforced) and not windows.in_window(window, at):
        raise Conflict(f"Calls can only be placed during calling hours: {windows.describe(window)}")
    await _expire_stale_calls(session)
    active = await session.scalar(select(func.count()).where(Call.status.in_(ACTIVE))) or 0
    if active >= settings.call_limit:
        raise TooManyRequests(f"{active} call(s) already in progress (limit {settings.call_limit})")

    instructions = build_instructions(config, person, data.context.get("items") or [], language)
    econfig = engine_config(config, instructions, language)
    call = Call(
        id=uuid.uuid7(),
        department_id=department_id,
        campaign_id=campaign.id if campaign else None,
        campaign_contact_id=campaign_contact.id if campaign_contact else None,
        attempt_no=campaign_contact.attempts if campaign_contact else 1,  # the dialer counts this attempt
        contact_id=contact.id if contact else None,
        initiated_by_id=actor.id,
        phone_encrypted=number.encrypted,
        phone_hash=number.hash,
        phone_masked=number.masked,
        script_version_id=version.id,
        ai_config={
            **engine.describe(econfig),
            "telephony": telephony.name,
            "language": language or config["languages"]["default"],
            "system_instruction": instructions,
            "guards": config.get("limits") or {},
        },
        context=data.context,
        provider=telephony.name,
        is_simulated=telephony.simulated,
        status=CallStatus.QUEUED,
    )

    # One call per number at a time, across the platform.
    lock_seconds = settings.max_call_seconds_hard + int(STALE_AFTER_EXTRA.total_seconds())
    if not await get_redis().set(_lock_key(number.hash), str(call.id), nx=True, ex=lock_seconds):
        raise Conflict("This number is already being called")

    session.add(call)
    audit.record(
        session,
        ctx,
        "call.place",
        actor=actor,
        entity_type="call",
        entity_id=call.id,
        department_id=department_id,
        changes={"phone_masked": number.masked, "script_version_id": version.id, "simulated": telephony.simulated},
    )
    await session.commit()

    try:
        call.provider_call_id = await telephony.place_call(number.e164, call_urls(call))
    except TelephonyError as exc:
        call.status = CallStatus.FAILED
        call.end_reason = "provider_error"
        call.error = str(exc)
        call.ended_at = _now()
        await session.commit()
        await _release_lock(call)
        raise CallingUnavailable(str(exc))
    call.status = CallStatus.DIALING
    call.started_at = _now()
    await session.commit()
    return call


# ---- provider callbacks ----


async def get_for_provider(session: AsyncSession, call_id: uuid.UUID, provider: str) -> Call | None:
    call = await session.get(Call, call_id, with_for_update=True)
    return call if call is not None and call.provider == provider else None


def _event_id(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def _record_event(session: AsyncSession, call: Call, event_type: str, payload: dict) -> bool:
    """Stores a provider event once. Returns False if this exact event was already received (a retry)."""
    masked = json.loads(phone.mask_numbers_in_text(json.dumps(payload, default=str)))
    result = await session.execute(
        insert(CallEvent)
        .values(
            id=uuid.uuid7(),
            call_id=call.id,
            provider=call.provider,
            provider_event_id=_event_id(payload),
            event_type=event_type,
            payload=masked,
            processed_at=_now(),
        )
        .on_conflict_do_nothing(index_elements=["provider", "provider_event_id"])
        .returning(CallEvent.id)
    )
    # A row comes back only if the insert happened (rowcount is not reliable for ORM-enabled inserts).
    return result.first() is not None


async def flow(session: AsyncSession, call: Call) -> dict:
    """The provider asks what to do with the answered call: stream it to us, or hang up."""
    await _record_event(session, call, "flow", {"call": str(call.id), "at": _now().isoformat()})
    if call.status in TERMINAL:
        await session.commit()
        return frejun.HANGUP_RESPONSE
    await session.commit()
    return frejun.flow_response(media_url(call))


async def status_event(session: AsyncSession, call: Call, payload: dict) -> None:
    status = frejun.mapped_status(payload)
    if not await _record_event(session, call, f"status:{status or 'unknown'}", payload):
        await session.commit()
        return  # duplicate delivery
    now = _now()
    if status is not None:
        new = CallStatus(status)
        if new == CallStatus.COMPLETED:
            new = after_provider_end(call.status)
        if new == CallStatus.IN_PROGRESS and can_move(call.status, new):
            call.status = new
            call.answered_at = call.answered_at or now
        elif new in TERMINAL and can_move(call.status, new):
            call.status = new
            call.end_reason = call.end_reason or new.value
            call.ended_at = call.ended_at or now
            if call.answered_at:
                call.duration_seconds = round((call.ended_at - call.answered_at).total_seconds())
            await _release_lock(call)
        elif new == CallStatus.RINGING and can_move(call.status, new):
            call.status = new
    recording = frejun.find(payload, frejun.RECORDING_KEYS)
    if recording and not await session.scalar(select(Recording.id).where(Recording.call_id == call.id)):
        # A reference to the provider's copy. Downloading it into our storage comes with recording access
        # controls (Phase 6).
        session.add(
            Recording(
                call_id=call.id, bucket=f"provider:{call.provider}", object_key=recording, content_type="audio/unknown"
            )
        )
    await session.commit()


# ---- the media session ----


async def claim_media(session: AsyncSession, call: Call) -> bool:
    """A call's media stream may be opened once, and only while the call is live."""
    if call.status in TERMINAL:
        return False
    if not await get_redis().set(f"call:media:{call.id}", "1", nx=True, ex=24 * 3600):
        return False
    if can_move(call.status, CallStatus.IN_PROGRESS):
        call.status = CallStatus.IN_PROGRESS
    call.answered_at = call.answered_at or _now()
    await _record_event(session, call, "media_connected", {"call": str(call.id), "at": _now().isoformat()})
    await session.commit()
    return True


async def session_setup(session: AsyncSession, call: Call) -> tuple[EngineConfig, dict, ScenarioController]:
    version = await session.get(ScriptVersion, call.script_version_id)
    econfig = engine_config(version.config, call.ai_config["system_instruction"], call.ai_config.get("language_hint"))
    scenario = ScenarioController(version.config, (call.context or {}).get("items") or [])
    return econfig, version.config.get("limits") or {}, scenario


def make_guard(limits: dict, started_at: float) -> ConversationGuard:
    return ConversationGuard(
        max_call_seconds=limits.get("max_call_seconds", 300),
        hard_max_seconds=get_settings().max_call_seconds_hard,
        silence_timeout_seconds=limits.get("silence_timeout_seconds", 8),
        max_silence_prompts=limits.get("max_silence_prompts", 2),
        max_turns=limits.get("max_turns", 40),
        started_at=started_at,
    )


async def finish(session: AsyncSession, call_id: uuid.UUID, result: SessionResult) -> Call:
    """Stores what happened on the call. Opt-outs go on the do-not-call list here, by rule, not by the agent."""
    call = await session.get(Call, call_id, with_for_update=True)
    now = _now()
    session.add(Transcript(call_id=call.id, turns=result.turns, languages=[]))
    call.outcome = result.outcome
    call.outcome_note = result.note
    call.end_reason = result.end_reason
    call.metrics = result.metrics
    call.answers = result.scenario
    call.error = result.error
    call.ended_at = call.ended_at or now
    if call.answered_at:
        call.duration_seconds = round((call.ended_at - call.answered_at).total_seconds())
    final = CallStatus.FAILED if result.error and not result.turns else CallStatus.COMPLETED
    if can_move(call.status, final):
        call.status = final

    if result.outcome == "opted_out" and not await is_suppressed(session, call.phone_hash, call.department_id):
        session.add(
            DoNotCall(
                phone_encrypted=call.phone_encrypted,
                phone_hash=call.phone_hash,
                phone_masked=call.phone_masked,
                department_id=call.department_id,
                reason="Asked not to be called again (during an AI call)",
                source="caller request",
            )
        )
    audit.record(
        session,
        None,
        "call.ended",
        actor_email="call controller",
        entity_type="call",
        entity_id=call.id,
        department_id=call.department_id,
        changes={
            "status": call.status,
            "end_reason": result.end_reason,
            "outcome": result.outcome,
            "turns": len(result.turns),
        },
    )
    await session.commit()
    await _release_lock(call)
    return call


# ---- users ----


async def _get(session: AsyncSession, actor: User, call_id: uuid.UUID) -> Call:
    call = await session.get(Call, call_id)
    if call is None or not can_see(actor, call.department_id):
        raise NotFound("Call not found")
    return call


async def hang_up(
    session: AsyncSession, actor: User, call_id: uuid.UUID, telephony: TelephonyProvider, ctx: RequestContext
) -> Call:
    call = await _get(session, actor, call_id)
    if call.status in TERMINAL:
        raise Conflict(f"The call is already {call.status}")
    if call.provider_call_id:
        await telephony.hangup(call.provider_call_id)
    if call.status != CallStatus.IN_PROGRESS:  # not answered yet: it ends here
        call.status = CallStatus.CANCELLED
        call.end_reason = "hung_up_by_user"
        call.ended_at = _now()
        await _release_lock(call)
    audit.record(
        session,
        ctx,
        "call.hang_up",
        actor=actor,
        entity_type="call",
        entity_id=call.id,
        department_id=call.department_id,
    )
    await session.commit()
    return call


async def list_calls(
    session: AsyncSession,
    actor: User,
    params: PageParams,
    status: CallStatus | None = None,
    contact_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
) -> tuple[list[CallOut], int]:
    query = select(Call, Contact.name).outerjoin(Contact, Contact.id == Call.contact_id)
    if (scope := visible_departments(actor)) is not None:
        query = query.where(Call.department_id.in_(scope))
    for column, value in ((Call.status, status), (Call.contact_id, contact_id), (Call.campaign_id, campaign_id)):
        if value is not None:
            query = query.where(column == value)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.execute(query.order_by(Call.created_at.desc()).offset(params.offset).limit(params.page_size))
    items = []
    for call, name in rows.all():
        out = CallOut.model_validate(call)
        out.contact_name = name
        items.append(out)
    return items, total or 0


async def get_call(session: AsyncSession, actor: User, call_id: uuid.UUID) -> CallDetail:
    call = await _get(session, actor, call_id)
    detail = CallDetail.model_validate(call)
    if call.contact_id:
        detail.contact_name = await session.scalar(select(Contact.name).where(Contact.id == call.contact_id))
    transcript = await session.scalar(select(Transcript).where(Transcript.call_id == call.id))
    detail.transcript = transcript.turns if transcript else []
    events = await session.scalars(
        select(CallEvent).where(CallEvent.call_id == call.id).order_by(CallEvent.received_at)
    )
    detail.events = [CallEventOut.model_validate(e) for e in events]
    recordings = await session.scalars(select(Recording).where(Recording.call_id == call.id))
    detail.recordings = [RecordingOut.model_validate(r) for r in recordings]
    extraction = await session.scalar(
        select(ExtractedResult).where(ExtractedResult.call_id == call.id).order_by(ExtractedResult.created_at.desc())
    )
    detail.extraction = ExtractionOut.model_validate(extraction) if extraction else None
    return detail
