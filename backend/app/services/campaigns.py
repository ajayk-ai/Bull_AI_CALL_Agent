"""Campaigns: set-up, contacts, and the approval workflow.

    draft -> pending_approval -> approved            (Phase 2)
    approved -> running <-> paused -> completed      (Phase 4, calling engine)
    any state except completed -> cancelled

Start, pause and resume are deliberately absent until the calling engine exists, so a campaign can never look
as if it is calling when it is not.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.models.campaigns import Campaign, CampaignApproval, CampaignContact
from app.models.contacts import Contact
from app.models.enums import ApprovalDecision, CampaignStatus, Role, ScriptVersionStatus
from app.models.org import User
from app.models.scripts import Script, ScriptVersion
from app.rbac.permissions import can_see, is_admin, resolve_department, visible_departments
from app.schemas.campaigns import (
    CallingWindow,
    CampaignContactOut,
    CampaignContactsAdd,
    CampaignCreate,
    CampaignOut,
    CampaignUpdate,
)
from app.schemas.common import PageParams
from app.services import audit
from app.services.contacts import dnc_active
from app.services.scripts import context_problems

_CANCELLABLE = {
    CampaignStatus.DRAFT,
    CampaignStatus.PENDING_APPROVAL,
    CampaignStatus.APPROVED,
    CampaignStatus.RUNNING,
    CampaignStatus.PAUSED,
}
# Fields a PATCH may change but not set to null.
_REQUIRED_FIELDS = ("name", "owner_id", "calling_window", "max_concurrency", "max_attempts", "retry_interval_minutes")
# How many failing contacts a submit error lists.
_PROBLEM_SAMPLE = 50


async def _get(session: AsyncSession, actor: User, campaign_id: uuid.UUID, *, for_update: bool = False) -> Campaign:
    campaign = await session.get(Campaign, campaign_id, with_for_update=for_update)
    if campaign is None or not can_see(actor, campaign.department_id):
        raise NotFound("Campaign not found")
    return campaign


def _require_draft(campaign: Campaign) -> None:
    if campaign.status != CampaignStatus.DRAFT:
        raise Conflict(f"Only draft campaigns can be changed; this campaign is {campaign.status}")


async def _out(session: AsyncSession, campaign: Campaign) -> CampaignOut:
    out = CampaignOut.model_validate(campaign)
    out.contact_count = (
        await session.scalar(select(func.count()).where(CampaignContact.campaign_id == campaign.id)) or 0
    )
    return out


async def _check_owner(session: AsyncSession, owner_id: uuid.UUID, department_id: uuid.UUID) -> None:
    owner = await session.get(User, owner_id)
    if (
        owner is None
        or not owner.is_active
        or owner.role not in (Role.CAMPAIGN_MANAGER, Role.HOD, Role.ADMIN)
        or (owner.role != Role.ADMIN and owner.department_id != department_id)
    ):
        raise ValidationFailed("Owner must be an active campaign manager, HOD or admin of the campaign's department")


async def _check_script_version(
    session: AsyncSession, version_id: uuid.UUID, department_id: uuid.UUID
) -> ScriptVersion:
    version = await session.get(ScriptVersion, version_id)
    script = await session.get(Script, version.script_id) if version else None
    if version is None or script is None or script.department_id != department_id:
        raise ValidationFailed("Script version not found in this department")
    if version.status != ScriptVersionStatus.PUBLISHED:
        raise ValidationFailed(f"Only published script versions can be used; this one is {version.status}")
    return version


def _check_language(language: str | None, version: ScriptVersion | None) -> None:
    if language and version and language not in version.config["languages"]["allowed"]:
        raise ValidationFailed(
            f"Language {language} is not allowed by the script; allowed: {version.config['languages']['allowed']}"
        )


async def create_campaign(session: AsyncSession, actor: User, data: CampaignCreate, ctx: RequestContext) -> CampaignOut:
    department_id = resolve_department(actor, data.department_id)
    owner_id = data.owner_id or actor.id
    await _check_owner(session, owner_id, department_id)
    version = (
        await _check_script_version(session, data.script_version_id, department_id) if data.script_version_id else None
    )
    _check_language(data.language, version)

    campaign = Campaign(
        department_id=department_id,
        name=data.name,
        description=data.description,
        owner_id=owner_id,
        script_version_id=data.script_version_id,
        language=data.language,
        start_date=data.start_date,
        end_date=data.end_date,
        calling_window=(data.calling_window or CallingWindow()).model_dump(mode="json"),
        created_by_id=actor.id,
        **{
            k: v
            for k, v in data.model_dump(include={"max_concurrency", "max_attempts", "retry_interval_minutes"}).items()
            if v is not None
        },
    )
    session.add(campaign)
    await session.flush()
    audit.record(
        session,
        ctx,
        "campaign.create",
        actor=actor,
        entity_type="campaign",
        entity_id=campaign.id,
        department_id=department_id,
        changes={"name": campaign.name, "script_version_id": campaign.script_version_id},
    )
    await session.commit()
    return await _out(session, campaign)


async def list_campaigns(
    session: AsyncSession,
    actor: User,
    params: PageParams,
    status: CampaignStatus | None = None,
    department_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
) -> tuple[list[CampaignOut], int]:
    query = select(Campaign)
    if (scope := visible_departments(actor)) is not None:
        query = query.where(Campaign.department_id.in_(scope))
    for column, value in (
        (Campaign.status, status),
        (Campaign.department_id, department_id),
        (Campaign.owner_id, owner_id),
    ):
        if value is not None:
            query = query.where(column == value)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(Campaign.created_at.desc()).offset(params.offset).limit(params.page_size)
    )
    return [await _out(session, c) for c in rows], total or 0


async def get_campaign(session: AsyncSession, actor: User, campaign_id: uuid.UUID) -> CampaignOut:
    return await _out(session, await _get(session, actor, campaign_id))


async def update_campaign(
    session: AsyncSession, actor: User, campaign_id: uuid.UUID, data: CampaignUpdate, ctx: RequestContext
) -> CampaignOut:
    campaign = await _get(session, actor, campaign_id, for_update=True)
    _require_draft(campaign)
    updates = data.model_dump(exclude_unset=True)
    cleared = [k for k in _REQUIRED_FIELDS if k in updates and updates[k] is None]
    if cleared:
        raise ValidationFailed(f"These fields cannot be cleared: {', '.join(cleared)}")
    if "owner_id" in updates:
        await _check_owner(session, updates["owner_id"], campaign.department_id)
    version_id = updates.get("script_version_id", campaign.script_version_id)
    version = await _check_script_version(session, version_id, campaign.department_id) if version_id else None
    _check_language(updates.get("language", campaign.language), version)
    start = updates.get("start_date", campaign.start_date)
    end = updates.get("end_date", campaign.end_date)
    if start and end and end < start:
        raise ValidationFailed("end_date must not be before start_date")
    if "calling_window" in updates:
        updates["calling_window"] = data.calling_window.model_dump(mode="json")

    changes = audit.diff({k: getattr(campaign, k) for k in updates}, updates)
    for key, value in updates.items():
        setattr(campaign, key, value)
    audit.record(
        session,
        ctx,
        "campaign.update",
        actor=actor,
        entity_type="campaign",
        entity_id=campaign.id,
        department_id=campaign.department_id,
        changes=changes,
    )
    await session.commit()
    return await _out(session, campaign)


# ---- contacts in a campaign ----


async def add_contacts(
    session: AsyncSession, actor: User, campaign_id: uuid.UUID, data: CampaignContactsAdd, ctx: RequestContext
) -> dict:
    campaign = await _get(session, actor, campaign_id, for_update=True)
    _require_draft(campaign)
    found = await session.scalars(
        select(Contact.id).where(
            Contact.id.in_(data.contact_ids),
            Contact.department_id == campaign.department_id,
            Contact.deleted_at.is_(None),
        )
    )
    valid_ids = set(found)
    missing = [str(i) for i in data.contact_ids if i not in valid_ids]
    if missing:
        raise ValidationFailed(
            "Some contacts do not exist in the campaign's department", details={"contact_ids": missing}
        )
    existing = set(
        await session.scalars(
            select(CampaignContact.contact_id).where(
                CampaignContact.campaign_id == campaign.id, CampaignContact.contact_id.in_(valid_ids)
            )
        )
    )
    added = [cid for cid in dict.fromkeys(data.contact_ids) if cid not in existing]
    session.add_all(CampaignContact(campaign_id=campaign.id, contact_id=cid, context=data.context) for cid in added)
    audit.record(
        session,
        ctx,
        "campaign.contacts_added",
        actor=actor,
        entity_type="campaign",
        entity_id=campaign.id,
        department_id=campaign.department_id,
        changes={"added": len(added), "already_present": len(existing)},
    )
    await session.commit()
    return {"added": len(added), "already_present": len(existing)}


async def remove_contact(
    session: AsyncSession, actor: User, campaign_id: uuid.UUID, contact_id: uuid.UUID, ctx: RequestContext
) -> None:
    campaign = await _get(session, actor, campaign_id, for_update=True)
    _require_draft(campaign)
    member = await session.scalar(
        select(CampaignContact).where(
            CampaignContact.campaign_id == campaign.id, CampaignContact.contact_id == contact_id
        )
    )
    if member is None:
        raise NotFound("Contact is not in this campaign")
    await session.delete(member)
    audit.record(
        session,
        ctx,
        "campaign.contact_removed",
        actor=actor,
        entity_type="campaign",
        entity_id=campaign.id,
        department_id=campaign.department_id,
        changes={"contact_id": contact_id},
    )
    await session.commit()


async def list_contacts(
    session: AsyncSession, actor: User, campaign_id: uuid.UUID, params: PageParams
) -> tuple[list[CampaignContactOut], int]:
    campaign = await _get(session, actor, campaign_id)
    dnc = dnc_active(Contact.phone_hash, Contact.department_id).label("do_not_call")
    query = (
        select(CampaignContact, Contact, dnc)
        .join(Contact, Contact.id == CampaignContact.contact_id)
        .where(CampaignContact.campaign_id == campaign.id)
    )
    total = await session.scalar(select(func.count()).where(CampaignContact.campaign_id == campaign.id))
    rows = await session.execute(query.order_by(Contact.name).offset(params.offset).limit(params.page_size))
    items = [
        CampaignContactOut(
            id=member.id,
            contact_id=contact.id,
            contact_name=contact.name,
            company=contact.company,
            phone_masked=contact.phone_masked,
            do_not_call=flag,
            status=member.status,
            attempts=member.attempts,
            outcome=member.outcome,
            context=member.context,
            created_at=member.created_at,
        )
        for member, contact, flag in rows.all()
    ]
    return items, total or 0


# ---- approval workflow ----


async def _readiness_problems(session: AsyncSession, campaign: Campaign) -> list[str]:
    problems: list[str] = []
    version = await session.get(ScriptVersion, campaign.script_version_id) if campaign.script_version_id else None
    if version is None:
        problems.append("No script version is assigned")
    elif version.status != ScriptVersionStatus.PUBLISHED:
        problems.append(f"The assigned script version is {version.status}, not published")
    if campaign.end_date and campaign.end_date < date.today():
        problems.append("The end date is in the past")

    members = (
        await session.execute(
            select(CampaignContact.context, Contact.name)
            .join(Contact, Contact.id == CampaignContact.contact_id)
            .where(CampaignContact.campaign_id == campaign.id, Contact.deleted_at.is_(None))
        )
    ).all()
    if not members:
        problems.append("The campaign has no contacts")
    elif version is not None:
        failing = [(name, issues) for context, name in members if (issues := context_problems(version.config, context))]
        for name, issues in failing[:_PROBLEM_SAMPLE]:
            problems.append(f"{name}: {'; '.join(issues)}")
        if len(failing) > _PROBLEM_SAMPLE:
            problems.append(f"... and {len(failing) - _PROBLEM_SAMPLE} more contacts with missing campaign data")
    return problems


async def submit(session: AsyncSession, actor: User, campaign_id: uuid.UUID, ctx: RequestContext) -> CampaignOut:
    campaign = await _get(session, actor, campaign_id, for_update=True)
    _require_draft(campaign)
    if problems := await _readiness_problems(session, campaign):
        raise ValidationFailed("Campaign is not ready for approval", details={"problems": problems})
    campaign.status = CampaignStatus.PENDING_APPROVAL
    session.add(CampaignApproval(campaign_id=campaign.id, requested_by_id=actor.id))
    audit.record(
        session,
        ctx,
        "campaign.submit",
        actor=actor,
        entity_type="campaign",
        entity_id=campaign.id,
        department_id=campaign.department_id,
    )
    await session.commit()
    return await _out(session, campaign)


async def _pending_approval(session: AsyncSession, campaign: Campaign) -> CampaignApproval:
    if campaign.status != CampaignStatus.PENDING_APPROVAL:
        raise Conflict(f"Campaign is {campaign.status}, not pending approval")
    approval = await _pending_approval_or_none(session, campaign.id)
    if approval is None:  # pending status without a request row would be a bug
        raise Conflict("No pending approval request found")
    return approval


async def decide(
    session: AsyncSession,
    actor: User,
    campaign_id: uuid.UUID,
    approve: bool,
    comments: str | None,
    ctx: RequestContext,
) -> CampaignOut:
    campaign = await _get(session, actor, campaign_id, for_update=True)
    approval = await _pending_approval(session, campaign)
    if approve and approval.requested_by_id == actor.id and not is_admin(actor):
        raise Forbidden("A campaign must be approved by someone other than the person who submitted it")
    if approve and (problems := await _readiness_problems(session, campaign)):
        raise ValidationFailed("Campaign is no longer ready for approval", details={"problems": problems})
    approval.decision = ApprovalDecision.APPROVED if approve else ApprovalDecision.REJECTED
    approval.decided_by_id = actor.id
    approval.decided_at = datetime.now(UTC)
    approval.comments = comments
    campaign.status = CampaignStatus.APPROVED if approve else CampaignStatus.DRAFT
    audit.record(
        session,
        ctx,
        "campaign.approve" if approve else "campaign.reject",
        actor=actor,
        entity_type="campaign",
        entity_id=campaign.id,
        department_id=campaign.department_id,
        changes={"comments": comments} if comments else {},
    )
    await session.commit()
    return await _out(session, campaign)


async def cancel(
    session: AsyncSession, actor: User, campaign_id: uuid.UUID, comments: str | None, ctx: RequestContext
) -> CampaignOut:
    campaign = await _get(session, actor, campaign_id, for_update=True)
    if campaign.status not in _CANCELLABLE:
        raise Conflict(f"A {campaign.status} campaign cannot be cancelled")
    previous = campaign.status
    campaign.status = CampaignStatus.CANCELLED
    if previous == CampaignStatus.PENDING_APPROVAL:
        approval = await _pending_approval_or_none(session, campaign.id)
        if approval:
            approval.decision = ApprovalDecision.REJECTED
            approval.decided_by_id = actor.id
            approval.decided_at = datetime.now(UTC)
            approval.comments = "Campaign cancelled"
    audit.record(
        session,
        ctx,
        "campaign.cancel",
        actor=actor,
        entity_type="campaign",
        entity_id=campaign.id,
        department_id=campaign.department_id,
        changes={"from": previous, **({"comments": comments} if comments else {})},
    )
    await session.commit()
    return await _out(session, campaign)


async def _pending_approval_or_none(session: AsyncSession, campaign_id: uuid.UUID) -> CampaignApproval | None:
    return await session.scalar(
        select(CampaignApproval).where(
            CampaignApproval.campaign_id == campaign_id, CampaignApproval.decision == ApprovalDecision.PENDING
        )
    )


async def list_approvals(session: AsyncSession, actor: User, campaign_id: uuid.UUID) -> list[CampaignApproval]:
    campaign = await _get(session, actor, campaign_id)
    rows = await session.scalars(
        select(CampaignApproval)
        .where(CampaignApproval.campaign_id == campaign.id)
        .order_by(CampaignApproval.requested_at.desc())
    )
    return list(rows)
