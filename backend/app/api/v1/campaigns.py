import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import ContextDep, SessionDep, require
from app.models.enums import CampaignStatus
from app.models.org import User
from app.rbac.permissions import Permission
from app.schemas.campaigns import (
    ApprovalOut,
    CampaignContactOut,
    CampaignContactsAdd,
    CampaignCreate,
    CampaignOut,
    CampaignUpdate,
)
from app.schemas.common import Page, PageParams
from app.schemas.scripts import ReviewDecision
from app.services import campaigns

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

ReadCampaigns = Annotated[User, Depends(require(Permission.CAMPAIGNS_READ))]
WriteCampaigns = Annotated[User, Depends(require(Permission.CAMPAIGNS_WRITE))]
ApproveCampaigns = Annotated[User, Depends(require(Permission.CAMPAIGNS_APPROVE))]


@router.get("", response_model=Page[CampaignOut])
async def list_campaigns(
    user: ReadCampaigns,
    session: SessionDep,
    params: Annotated[PageParams, Query()],
    status: CampaignStatus | None = None,
    department_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
):
    items, total = await campaigns.list_campaigns(session, user, params, status, department_id, owner_id)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.post("", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
async def create_campaign(body: CampaignCreate, user: WriteCampaigns, session: SessionDep, ctx: ContextDep):
    return await campaigns.create_campaign(session, user, body, ctx)


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: uuid.UUID, user: ReadCampaigns, session: SessionDep):
    return await campaigns.get_campaign(session, user, campaign_id)


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: uuid.UUID, body: CampaignUpdate, user: WriteCampaigns, session: SessionDep, ctx: ContextDep
):
    return await campaigns.update_campaign(session, user, campaign_id, body, ctx)


@router.get("/{campaign_id}/contacts", response_model=Page[CampaignContactOut])
async def list_campaign_contacts(
    campaign_id: uuid.UUID, user: ReadCampaigns, session: SessionDep, params: Annotated[PageParams, Query()]
):
    items, total = await campaigns.list_contacts(session, user, campaign_id, params)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.post("/{campaign_id}/contacts")
async def add_campaign_contacts(
    campaign_id: uuid.UUID, body: CampaignContactsAdd, user: WriteCampaigns, session: SessionDep, ctx: ContextDep
) -> dict:
    return await campaigns.add_contacts(session, user, campaign_id, body, ctx)


@router.delete("/{campaign_id}/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_campaign_contact(
    campaign_id: uuid.UUID, contact_id: uuid.UUID, user: WriteCampaigns, session: SessionDep, ctx: ContextDep
) -> None:
    await campaigns.remove_contact(session, user, campaign_id, contact_id, ctx)


@router.post("/{campaign_id}/submit", response_model=CampaignOut)
async def submit_campaign(campaign_id: uuid.UUID, user: WriteCampaigns, session: SessionDep, ctx: ContextDep):
    """Checks the campaign is complete (published script, contacts, campaign data) and requests approval."""
    return await campaigns.submit(session, user, campaign_id, ctx)


@router.post("/{campaign_id}/approve", response_model=CampaignOut)
async def approve_campaign(
    campaign_id: uuid.UUID, body: ReviewDecision, user: ApproveCampaigns, session: SessionDep, ctx: ContextDep
):
    return await campaigns.decide(session, user, campaign_id, True, body.comments, ctx)


@router.post("/{campaign_id}/reject", response_model=CampaignOut)
async def reject_campaign(
    campaign_id: uuid.UUID, body: ReviewDecision, user: ApproveCampaigns, session: SessionDep, ctx: ContextDep
):
    return await campaigns.decide(session, user, campaign_id, False, body.comments, ctx)


@router.post("/{campaign_id}/cancel", response_model=CampaignOut)
async def cancel_campaign(
    campaign_id: uuid.UUID, body: ReviewDecision, user: WriteCampaigns, session: SessionDep, ctx: ContextDep
):
    return await campaigns.cancel(session, user, campaign_id, body.comments, ctx)


@router.get("/{campaign_id}/approvals", response_model=list[ApprovalOut])
async def list_approvals(campaign_id: uuid.UUID, user: ReadCampaigns, session: SessionDep):
    return await campaigns.list_approvals(session, user, campaign_id)
