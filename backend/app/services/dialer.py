"""The campaign dialer: calls a running campaign's contacts one after another on the available channels.

Every few seconds (DIALER_INTERVAL_SECONDS) one tick runs:

1. Settle: each campaign contact whose call has ended gets its result. An answered call that reached the end
   completes the contact. No answer, busy, failure or a call that ended before anyone spoke schedules a retry
   after the campaign's retry interval, up to its maximum attempts.
2. If every channel is busy (CALL_CHANNELS, 1 by default), stop: the next call waits for the current one.
3. Otherwise place the next due contact of the oldest running campaign that is inside its calling window.
   The usual call checks apply (do-not-call, calling hours, one call per number). A contact that may not be
   called (e.g. on the do-not-call list) is skipped with the reason.
4. A running campaign with nobody left to call is completed.

The dialer runs inside the web process (one worker), guarded by a Redis lease so a second process never dials
at the same time. Celery workers can take this over when more channels are added.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Conflict, NotFound, TooManyRequests, ValidationFailed
from app.core.redis import get_redis
from app.db.session import get_sessionmaker
from app.models.calls import Call, Transcript
from app.models.campaigns import Campaign, CampaignContact
from app.models.enums import CallStatus, CampaignContactStatus, CampaignStatus
from app.models.org import User
from app.schemas.calls import CallCreate
from app.services import audit, calls, windows
from app.voice.fsm import ACTIVE, TERMINAL

log = logging.getLogger(__name__)

LEASE_KEY = "dialer:lease"
# Outcomes that finish a contact. Anything else (no answer, busy, an early hang-up) is worth another attempt.
FINAL_OUTCOMES = {"completed", "wrong_person", "callback_requested", "opted_out", "refused"}
WAITING = (CampaignContactStatus.PENDING, CampaignContactStatus.RETRY_SCHEDULED)


def _now() -> datetime:
    return datetime.now(UTC)


async def _settle(session: AsyncSession, now: datetime) -> None:
    in_progress = await session.scalars(
        select(CampaignContact).where(CampaignContact.status == CampaignContactStatus.IN_PROGRESS)
    )
    for cc in in_progress:
        call = await session.scalar(
            select(Call).where(Call.campaign_contact_id == cc.id).order_by(Call.created_at.desc()).limit(1)
        )
        if call is not None and call.status not in TERMINAL:
            continue
        campaign = await session.get(Campaign, cc.campaign_id)
        spoke = call is not None and bool(
            await session.scalar(select(Transcript.turns).where(Transcript.call_id == call.id))
        )
        if call is not None and call.status == CallStatus.COMPLETED and spoke and call.outcome in FINAL_OUTCOMES:
            cc.status = CampaignContactStatus.COMPLETED
            cc.outcome = call.outcome
        elif cc.attempts < campaign.max_attempts:
            cc.status = CampaignContactStatus.RETRY_SCHEDULED
            cc.next_attempt_at = now + timedelta(minutes=campaign.retry_interval_minutes)
            cc.outcome = (call.outcome or call.end_reason or str(call.status)) if call else "not placed"
        else:
            cc.status = CampaignContactStatus.FAILED
            cc.outcome = (call.outcome or call.end_reason or str(call.status)) if call else "not placed"
    await session.commit()


async def _next_contact(session: AsyncSession, campaign: Campaign, now: datetime) -> CampaignContact | None:
    due = (CampaignContact.status == CampaignContactStatus.PENDING) | (
        (CampaignContact.status == CampaignContactStatus.RETRY_SCHEDULED) & (CampaignContact.next_attempt_at <= now)
    )
    return await session.scalar(
        select(CampaignContact)
        .where(CampaignContact.campaign_id == campaign.id, due)
        .order_by(CampaignContact.next_attempt_at.nulls_first(), CampaignContact.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


async def _finish_if_done(session: AsyncSession, campaign: Campaign) -> bool:
    left = await session.scalar(
        select(func.count()).where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.status.in_([*WAITING, CampaignContactStatus.IN_PROGRESS, CampaignContactStatus.QUEUED]),
        )
    )
    if left:
        return False
    campaign.status = CampaignStatus.COMPLETED
    audit.record(
        session,
        None,
        "campaign.completed",
        actor_email="campaign dialer",
        entity_type="campaign",
        entity_id=campaign.id,
        department_id=campaign.department_id,
    )
    await session.commit()
    log.info("Campaign %s completed", campaign.id)
    return True


async def tick(session: AsyncSession, telephony, engine, now: datetime | None = None) -> Call | None:
    """One pass of the dialer. Returns the call it placed, if any."""
    now = now or _now()
    await _settle(session, now)

    active = await session.scalar(select(func.count()).where(Call.status.in_(ACTIVE))) or 0
    if active >= get_settings().call_limit:
        return None

    running = await session.scalars(
        select(Campaign).where(Campaign.status == CampaignStatus.RUNNING).order_by(Campaign.created_at)
    )
    for campaign in list(running):
        if await _finish_if_done(session, campaign):
            continue
        if not windows.in_window(campaign.calling_window or {}, now):
            continue
        cc = await _next_contact(session, campaign, now)
        if cc is None:
            continue
        owner = await session.get(User, campaign.owner_id)
        data = CallCreate(
            contact_id=cc.contact_id,
            script_version_id=campaign.script_version_id,
            language=campaign.language,
            context=cc.context or {},
        )
        # A rollback expires loaded objects, so log with plain values.
        campaign_id, cc_id, contact_id = campaign.id, cc.id, cc.contact_id
        cc.status = CampaignContactStatus.IN_PROGRESS
        cc.attempts += 1
        cc.last_attempt_at = now
        try:
            # place_call commits: the contact is marked in progress together with the new call.
            call = await calls.place_call(
                session, owner, data, telephony, engine, None, at=now, campaign=campaign, campaign_contact=cc
            )
        except TooManyRequests:  # another call took the channel in the meantime
            await session.rollback()
            return None
        except calls.CallingUnavailable as exc:  # the provider refused; settled and retried like a failed call
            log.warning("Campaign %s: call to contact %s failed: %s", campaign_id, contact_id, exc)
            return None
        except (ValidationFailed, NotFound, Conflict) as exc:
            await session.rollback()
            if isinstance(exc, Conflict) and "do-not-call" not in str(exc):
                # e.g. someone else is calling this number right now: the contact stays due for a later tick
                log.info("Campaign %s: contact %s not called now: %s", campaign_id, contact_id, exc)
                return None
            # May never be called as things stand (do-not-call, missing data, ...): skip it with the reason.
            skipped = await session.get(CampaignContact, cc_id)
            skipped.status = CampaignContactStatus.SKIPPED
            skipped.outcome = str(exc)[:64]
            await session.commit()
            log.info("Campaign %s: contact %s skipped: %s", campaign_id, contact_id, exc)
            return None
        log.info("Campaign %s: calling contact %s (attempt %d)", campaign.id, cc.contact_id, cc.attempts)
        return call
    return None


# ---- the background loop ----


async def run_forever(telephony_factory, engine_factory, stop: asyncio.Event) -> None:
    settings = get_settings()
    interval = settings.dialer_interval_seconds
    log.info("Campaign dialer started: %d channel(s), every %.0f s", settings.call_limit, interval)
    me = uuid.uuid4().hex
    while not stop.is_set():
        try:
            # A lease held by this process and renewed every tick, so only one process dials.
            redis = get_redis()
            lease = int(interval * 4) + 5
            held = await redis.set(LEASE_KEY, me, nx=True, ex=lease)
            if not held and await redis.get(LEASE_KEY) == me:
                held = await redis.expire(LEASE_KEY, lease)
            if held:
                async with get_sessionmaker()() as session:
                    await tick(session, telephony_factory(), engine_factory())
        except Exception:
            log.exception("Campaign dialer tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
