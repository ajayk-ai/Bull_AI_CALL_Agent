"""Audit trail. Entries are added to the caller's session, so they commit (or roll back) with the change."""

import uuid
from datetime import datetime
from typing import Any

from pydantic_core import to_jsonable_python
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.models.audit import AuditLog
from app.models.org import User
from app.rbac.permissions import visible_departments
from app.schemas.common import PageParams

# Never written to the audit log in clear text.
_REDACT = {"password", "password_hash", "phone", "phone_encrypted", "phone_hash", "credentials", "secrets"}


def _clean(changes: dict[str, Any]) -> dict[str, Any]:
    return to_jsonable_python({k: ("[redacted]" if k in _REDACT else v) for k, v in changes.items()})


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """{"field": {"from": old, "to": new}} for fields that changed."""
    return {k: {"from": before.get(k), "to": v} for k, v in after.items() if before.get(k) != v}


def record(
    session: AsyncSession,
    ctx: RequestContext | None,
    action: str,
    *,
    actor: User | None = None,
    actor_email: str | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    changes: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        actor_email=(actor.email or actor.username) if actor else actor_email,
        department_id=department_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        changes=_clean(changes or {}),
        ip_address=ctx.ip_address if ctx else None,
        user_agent=ctx.user_agent if ctx else None,
        request_id=ctx.request_id if ctx else None,
    )
    session.add(entry)
    return entry


async def list_entries(
    session: AsyncSession,
    actor: User,
    params: PageParams,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> tuple[list[AuditLog], int]:
    query = select(AuditLog)
    if (scope := visible_departments(actor)) is not None:
        query = query.where(AuditLog.department_id.in_(scope))
    filters = {
        AuditLog.entity_type: entity_type,
        AuditLog.entity_id: entity_id,
        AuditLog.actor_id: actor_id,
        AuditLog.action: action,
    }
    query = query.where(*(column == value for column, value in filters.items() if value is not None))
    if since:
        query = query.where(AuditLog.occurred_at >= since)
    if until:
        query = query.where(AuditLog.occurred_at < until)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(AuditLog.occurred_at.desc()).offset(params.offset).limit(params.page_size)
    )
    return list(rows), total or 0
