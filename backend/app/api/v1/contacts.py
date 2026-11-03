import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import ContextDep, SessionDep, require
from app.models.org import User
from app.rbac.permissions import Permission
from app.schemas.audit import AuditLogOut
from app.schemas.common import LanguageCode, Page, PageParams
from app.schemas.contacts import (
    ConsentCreate,
    ConsentOut,
    ContactCreate,
    ContactOut,
    ContactPhoneOut,
    ContactUpdate,
    DncCreate,
    DncOut,
)
from app.services import audit, contacts

router = APIRouter(tags=["contacts and compliance"])

ReadContacts = Annotated[User, Depends(require(Permission.CONTACTS_READ))]
WriteContacts = Annotated[User, Depends(require(Permission.CONTACTS_WRITE))]
DeleteContacts = Annotated[User, Depends(require(Permission.CONTACTS_DELETE))]
ViewFullNumber = Annotated[User, Depends(require(Permission.CONTACTS_VIEW_FULL_NUMBER))]
WriteConsent = Annotated[User, Depends(require(Permission.CONSENT_WRITE))]
ReadDnc = Annotated[User, Depends(require(Permission.DNC_READ))]
WriteDnc = Annotated[User, Depends(require(Permission.DNC_WRITE))]
DeleteDnc = Annotated[User, Depends(require(Permission.DNC_DELETE))]
ReadAudit = Annotated[User, Depends(require(Permission.AUDIT_READ))]


@router.get("/contacts", response_model=Page[ContactOut])
async def list_contacts(
    user: ReadContacts,
    session: SessionDep,
    params: Annotated[PageParams, Query()],
    search: Annotated[str | None, Query(max_length=100, description="Name, company or full phone number")] = None,
    department_id: uuid.UUID | None = None,
    language: LanguageCode | None = None,
):
    items, total = await contacts.list_contacts(session, user, params, search, department_id, language)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.post("/contacts", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
async def create_contact(body: ContactCreate, user: WriteContacts, session: SessionDep, ctx: ContextDep):
    return await contacts.create_contact(session, user, body, ctx)


@router.get("/contacts/{contact_id}", response_model=ContactOut)
async def get_contact(contact_id: uuid.UUID, user: ReadContacts, session: SessionDep):
    return await contacts.get_contact(session, user, contact_id)


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
async def update_contact(
    contact_id: uuid.UUID, body: ContactUpdate, user: WriteContacts, session: SessionDep, ctx: ContextDep
):
    return await contacts.update_contact(session, user, contact_id, body, ctx)


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(contact_id: uuid.UUID, user: DeleteContacts, session: SessionDep, ctx: ContextDep) -> None:
    await contacts.delete_contact(session, user, contact_id, ctx)


@router.get("/contacts/{contact_id}/phone", response_model=ContactPhoneOut)
async def reveal_phone(contact_id: uuid.UUID, user: ViewFullNumber, session: SessionDep, ctx: ContextDep):
    """Returns the unmasked number. Each call is written to the audit log."""
    return ContactPhoneOut(id=contact_id, phone=await contacts.reveal_phone(session, user, contact_id, ctx))


@router.get("/contacts/{contact_id}/consents", response_model=list[ConsentOut])
async def list_consent(contact_id: uuid.UUID, user: ReadContacts, session: SessionDep):
    return await contacts.list_consent(session, user, contact_id)


@router.post("/contacts/{contact_id}/consents", response_model=ConsentOut, status_code=status.HTTP_201_CREATED)
async def add_consent(
    contact_id: uuid.UUID, body: ConsentCreate, user: WriteConsent, session: SessionDep, ctx: ContextDep
):
    return await contacts.add_consent(session, user, contact_id, body, ctx)


@router.get("/dnc", response_model=Page[DncOut])
async def list_dnc(
    user: ReadDnc,
    session: SessionDep,
    params: Annotated[PageParams, Query()],
    phone: Annotated[str | None, Query(max_length=32, description="Exact number to look up")] = None,
):
    items, total = await contacts.list_dnc(session, user, params, phone)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.post("/dnc", response_model=DncOut, status_code=status.HTTP_201_CREATED)
async def add_dnc(body: DncCreate, user: WriteDnc, session: SessionDep, ctx: ContextDep):
    return await contacts.add_dnc(session, user, body, ctx)


@router.delete("/dnc/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_dnc(entry_id: uuid.UUID, user: DeleteDnc, session: SessionDep, ctx: ContextDep) -> None:
    await contacts.remove_dnc(session, user, entry_id, ctx)


@router.get("/audit-logs", response_model=Page[AuditLogOut], tags=["audit"])
async def list_audit_logs(
    user: ReadAudit,
    session: SessionDep,
    params: Annotated[PageParams, Query()],
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
):
    items, total = await audit.list_entries(
        session,
        user,
        params,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        since=since,
        until=until,
    )
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)
