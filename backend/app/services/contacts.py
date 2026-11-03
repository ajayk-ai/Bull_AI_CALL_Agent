"""Contacts, consent records and the do-not-call (suppression) list."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import phone
from app.core.context import RequestContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.security import decrypt
from app.models.contacts import ConsentRecord, Contact, DoNotCall
from app.models.org import Department, User
from app.rbac.permissions import Permission, can_see, has_permission, resolve_department, visible_departments
from app.schemas.common import PageParams
from app.schemas.contacts import ConsentCreate, ContactCreate, ContactOut, ContactUpdate, DncCreate
from app.services import audit


def _normalise(raw: str) -> phone.NormalisedPhone:
    try:
        return phone.normalise(raw)
    except phone.InvalidPhoneNumber as exc:
        raise ValidationFailed(str(exc), details={"field": "phone"})


async def _require_active_department(session: AsyncSession, department_id: uuid.UUID) -> None:
    department = await session.get(Department, department_id)
    if department is None or not department.is_active:
        raise ValidationFailed("Department does not exist or is inactive")


# ---- do-not-call ----


def dnc_active(phone_hash: ColumnElement | str, department_id: ColumnElement | uuid.UUID) -> ColumnElement[bool]:
    """SQL condition: an unexpired DNC entry covers this number, globally or for this department."""
    return exists().where(
        DoNotCall.phone_hash == phone_hash,
        or_(DoNotCall.department_id.is_(None), DoNotCall.department_id == department_id),
        or_(DoNotCall.expires_at.is_(None), DoNotCall.expires_at > func.now()),
    )


async def is_suppressed(session: AsyncSession, phone_hash: str, department_id: uuid.UUID) -> bool:
    """Checked again at dial time by the calling engine; never rely on an earlier check alone."""
    return bool(await session.scalar(select(dnc_active(phone_hash, department_id))))


async def add_dnc(session: AsyncSession, actor: User, data: DncCreate, ctx: RequestContext) -> DoNotCall:
    if data.global_scope:
        if not has_permission(actor, Permission.DNC_GLOBAL):
            raise Forbidden("Only admins can add a number to the global do-not-call list")
        department_id = None
    else:
        department_id = resolve_department(actor, data.department_id)
    number = _normalise(data.phone)
    duplicate = await session.scalar(
        select(DoNotCall).where(
            DoNotCall.phone_hash == number.hash,
            DoNotCall.department_id.is_(None) if department_id is None else DoNotCall.department_id == department_id,
        )
    )
    if duplicate:
        raise Conflict("This number is already on the do-not-call list", details={"id": str(duplicate.id)})
    entry = DoNotCall(
        phone_encrypted=number.encrypted,
        phone_hash=number.hash,
        phone_masked=number.masked,
        department_id=department_id,
        reason=data.reason,
        source=data.source,
        expires_at=data.expires_at,
        added_by_id=actor.id,
    )
    session.add(entry)
    await session.flush()
    audit.record(
        session,
        ctx,
        "dnc.add",
        actor=actor,
        entity_type="do_not_call",
        entity_id=entry.id,
        department_id=department_id,
        changes={"phone_masked": number.masked, "reason": data.reason, "global": department_id is None},
    )
    await session.commit()
    return entry


async def list_dnc(
    session: AsyncSession, actor: User, params: PageParams, phone_query: str | None
) -> tuple[list[DoNotCall], int]:
    query = select(DoNotCall)
    if (scope := visible_departments(actor)) is not None:
        query = query.where(or_(DoNotCall.department_id.is_(None), DoNotCall.department_id.in_(scope)))
    if phone_query:
        query = query.where(DoNotCall.phone_hash == _normalise(phone_query).hash)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(DoNotCall.created_at.desc()).offset(params.offset).limit(params.page_size)
    )
    return list(rows), total or 0


async def remove_dnc(session: AsyncSession, actor: User, entry_id: uuid.UUID, ctx: RequestContext) -> None:
    entry = await session.get(DoNotCall, entry_id)
    if entry is None or not (can_see(actor, entry.department_id) or entry.department_id is None):
        raise NotFound("Do-not-call entry not found")
    if entry.department_id is None and not has_permission(actor, Permission.DNC_GLOBAL):
        raise Forbidden("Only admins can remove a global do-not-call entry")
    audit.record(
        session,
        ctx,
        "dnc.remove",
        actor=actor,
        entity_type="do_not_call",
        entity_id=entry.id,
        department_id=entry.department_id,
        changes={"phone_masked": entry.phone_masked, "reason": entry.reason},
    )
    await session.delete(entry)
    await session.commit()


# ---- contacts ----


def _out(contact: Contact, do_not_call: bool) -> ContactOut:
    out = ContactOut.model_validate(contact)
    out.do_not_call = do_not_call
    return out


async def _find_live_duplicate(
    session: AsyncSession, department_id: uuid.UUID, phone_hash: str, exclude: uuid.UUID | None = None
) -> Contact | None:
    query = select(Contact).where(
        Contact.department_id == department_id, Contact.phone_hash == phone_hash, Contact.deleted_at.is_(None)
    )
    if exclude:
        query = query.where(Contact.id != exclude)
    return await session.scalar(query)


async def _get_contact(session: AsyncSession, actor: User, contact_id: uuid.UUID) -> Contact:
    contact = await session.get(Contact, contact_id)
    if contact is None or contact.deleted_at is not None or not can_see(actor, contact.department_id):
        raise NotFound("Contact not found")
    return contact


async def get_contact(session: AsyncSession, actor: User, contact_id: uuid.UUID) -> ContactOut:
    contact = await _get_contact(session, actor, contact_id)
    return _out(contact, await is_suppressed(session, contact.phone_hash, contact.department_id))


async def create_contact(session: AsyncSession, actor: User, data: ContactCreate, ctx: RequestContext) -> ContactOut:
    department_id = resolve_department(actor, data.department_id)
    await _require_active_department(session, department_id)
    number = _normalise(data.phone)
    if existing := await _find_live_duplicate(session, department_id, number.hash):
        raise Conflict(
            "A contact with this phone number already exists in this department",
            details={"existing_contact_id": str(existing.id)},
        )
    contact = Contact(
        department_id=department_id,
        name=data.name,
        company=data.company,
        phone_encrypted=number.encrypted,
        phone_hash=number.hash,
        phone_masked=number.masked,
        language=data.language,
        custom_fields=data.custom_fields,
        created_by_id=actor.id,
    )
    session.add(contact)
    try:
        await session.flush()
    except IntegrityError:  # a concurrent request added the same number
        await session.rollback()
        raise Conflict("A contact with this phone number already exists in this department")
    audit.record(
        session,
        ctx,
        "contact.create",
        actor=actor,
        entity_type="contact",
        entity_id=contact.id,
        department_id=department_id,
        changes={"name": contact.name, "company": contact.company, "phone_masked": number.masked},
    )
    await session.commit()
    return _out(contact, await is_suppressed(session, contact.phone_hash, department_id))


async def list_contacts(
    session: AsyncSession,
    actor: User,
    params: PageParams,
    search: str | None = None,
    department_id: uuid.UUID | None = None,
    language: str | None = None,
) -> tuple[list[ContactOut], int]:
    dnc = dnc_active(Contact.phone_hash, Contact.department_id).label("do_not_call")
    query = select(Contact, dnc).where(Contact.deleted_at.is_(None))
    if (scope := visible_departments(actor)) is not None:
        query = query.where(Contact.department_id.in_(scope))
    if department_id:
        query = query.where(Contact.department_id == department_id)
    if language:
        query = query.where(Contact.language == language)
    if search:
        conditions = [Contact.name.ilike(f"%{search}%"), Contact.company.ilike(f"%{search}%")]
        try:
            conditions.append(Contact.phone_hash == phone.normalise(search).hash)
        except phone.InvalidPhoneNumber:
            pass
        query = query.where(or_(*conditions))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.execute(query.order_by(Contact.name).offset(params.offset).limit(params.page_size))
    return [_out(contact, flag) for contact, flag in rows.all()], total or 0


async def update_contact(
    session: AsyncSession, actor: User, contact_id: uuid.UUID, data: ContactUpdate, ctx: RequestContext
) -> ContactOut:
    contact = await _get_contact(session, actor, contact_id)
    updates = data.model_dump(exclude_unset=True)
    before = {k: getattr(contact, k) for k in updates if k != "phone"}
    changes = audit.diff(before, {k: v for k, v in updates.items() if k != "phone"})

    if raw := updates.pop("phone", None):
        number = _normalise(raw)
        if number.hash != contact.phone_hash:
            if existing := await _find_live_duplicate(session, contact.department_id, number.hash, exclude=contact.id):
                raise Conflict(
                    "Another contact in this department has this phone number",
                    details={"existing_contact_id": str(existing.id)},
                )
            changes["phone_masked"] = {"from": contact.phone_masked, "to": number.masked}
            contact.phone_encrypted, contact.phone_hash, contact.phone_masked = (
                number.encrypted,
                number.hash,
                number.masked,
            )
    for key, value in updates.items():
        setattr(contact, key, value)
    audit.record(
        session,
        ctx,
        "contact.update",
        actor=actor,
        entity_type="contact",
        entity_id=contact.id,
        department_id=contact.department_id,
        changes=changes,
    )
    await session.commit()
    return _out(contact, await is_suppressed(session, contact.phone_hash, contact.department_id))


async def delete_contact(session: AsyncSession, actor: User, contact_id: uuid.UUID, ctx: RequestContext) -> None:
    """Soft delete: call history and consent evidence still refer to the contact."""
    contact = await _get_contact(session, actor, contact_id)
    contact.deleted_at = datetime.now(UTC)
    audit.record(
        session,
        ctx,
        "contact.delete",
        actor=actor,
        entity_type="contact",
        entity_id=contact.id,
        department_id=contact.department_id,
        changes={"phone_masked": contact.phone_masked},
    )
    await session.commit()


async def reveal_phone(session: AsyncSession, actor: User, contact_id: uuid.UUID, ctx: RequestContext) -> str:
    """Full number. Every reveal is audited."""
    contact = await _get_contact(session, actor, contact_id)
    audit.record(
        session,
        ctx,
        "contact.phone_revealed",
        actor=actor,
        entity_type="contact",
        entity_id=contact.id,
        department_id=contact.department_id,
    )
    await session.commit()
    return decrypt(contact.phone_encrypted)


# ---- consent ----


async def add_consent(
    session: AsyncSession, actor: User, contact_id: uuid.UUID, data: ConsentCreate, ctx: RequestContext
) -> ConsentRecord:
    contact = await _get_contact(session, actor, contact_id)
    record = ConsentRecord(
        contact_id=contact.id,
        consent_type=data.consent_type,
        status=data.status,
        source=data.source,
        notes=data.notes,
        captured_by_id=actor.id,
        **({"captured_at": data.captured_at} if data.captured_at else {}),
    )
    session.add(record)
    await session.flush()
    audit.record(
        session,
        ctx,
        "consent.record",
        actor=actor,
        entity_type="contact",
        entity_id=contact.id,
        department_id=contact.department_id,
        changes={"consent_type": data.consent_type, "status": data.status, "source": data.source},
    )
    await session.commit()
    return record


async def list_consent(session: AsyncSession, actor: User, contact_id: uuid.UUID) -> list[ConsentRecord]:
    contact = await _get_contact(session, actor, contact_id)
    rows = await session.scalars(
        select(ConsentRecord)
        .where(ConsentRecord.contact_id == contact.id)
        .order_by(ConsentRecord.captured_at.desc(), ConsentRecord.created_at.desc())
    )
    return list(rows)
