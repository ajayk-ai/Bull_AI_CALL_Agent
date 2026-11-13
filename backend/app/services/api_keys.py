"""API keys: how other systems and AI assistants (over MCP) call this platform.

A key acts as the user who created it, limited to its access level (see API_KEY_ACCESS), and stops working when
it is revoked or expires, or when that user is deactivated or moves department. Only a SHA-256 of the key is
stored; the key itself is shown once.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.errors import NotFound, Unauthorized, ValidationFailed
from app.db.session import get_sessionmaker
from app.models.integrations import ApiKey
from app.models.org import User
from app.rbac.permissions import is_admin
from app.schemas.api_keys import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from app.services import audit

PREFIX = "bmk_"
MAX_ACTIVE_KEYS_PER_USER = 20
_TOUCH_EVERY = timedelta(minutes=1)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def looks_like_key(token: str) -> bool:
    return token.startswith(PREFIX)


async def authenticate(session: AsyncSession, token: str) -> tuple[ApiKey, User]:
    key = await session.scalar(select(ApiKey).where(ApiKey.key_hash == _hash(token)))
    now = datetime.now(UTC)
    if key is None or key.revoked_at is not None or (key.expires_at is not None and key.expires_at <= now):
        raise Unauthorized("Invalid, revoked or expired API key")
    user = await session.get(User, key.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("The account this API key belongs to is deactivated")
    if not is_admin(user) and user.department_id != key.department_id:
        raise Unauthorized("The key's owner has moved department; create a new key")
    if key.last_used_at is None or now - key.last_used_at > _TOUCH_EVERY:
        # Its own session, so the request's session has nothing pending from authentication.
        async with get_sessionmaker()() as other:
            await other.execute(update(ApiKey).where(ApiKey.id == key.id).values(last_used_at=now))
            await other.commit()
    return key, user


async def _out(session: AsyncSession, keys: list[ApiKey]) -> list[ApiKeyOut]:
    names = dict(
        (await session.execute(select(User.id, User.full_name).where(User.id.in_({k.user_id for k in keys})))).all()
    )
    return [ApiKeyOut.model_validate(k).model_copy(update={"user_name": names.get(k.user_id)}) for k in keys]


async def list_keys(session: AsyncSession, actor: User) -> list[ApiKeyOut]:
    """Admins see every key; others see their own."""
    query = select(ApiKey).order_by(ApiKey.created_at.desc())
    if not is_admin(actor):
        query = query.where(ApiKey.user_id == actor.id)
    return await _out(session, list(await session.scalars(query)))


async def create(session: AsyncSession, actor: User, body: ApiKeyCreate, ctx: RequestContext) -> ApiKeyCreated:
    active = await session.scalar(
        select(func.count()).where(
            ApiKey.user_id == actor.id,
            ApiKey.revoked_at.is_(None),
            (ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > datetime.now(UTC)),
        )
    )
    if active >= MAX_ACTIVE_KEYS_PER_USER:
        raise ValidationFailed(f"You can have at most {MAX_ACTIVE_KEYS_PER_USER} active keys; revoke one first")
    token = PREFIX + secrets.token_urlsafe(32)
    key = ApiKey(
        name=body.name,
        prefix=token[:12],
        key_hash=_hash(token),
        user_id=actor.id,
        department_id=actor.department_id,
        access=body.access,
        expires_at=datetime.now(UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days else None,
    )
    session.add(key)
    await session.flush()
    audit.record(
        session,
        ctx,
        "api_key.create",
        actor=actor,
        entity_type="api_key",
        entity_id=key.id,
        department_id=actor.department_id,
        changes={"name": body.name, "access": body.access, "prefix": key.prefix, "expires_at": str(key.expires_at)},
    )
    await session.commit()
    await session.refresh(key)
    (out,) = await _out(session, [key])
    return ApiKeyCreated(**out.model_dump(), key=token)


async def revoke(session: AsyncSession, actor: User, key_id: uuid.UUID, ctx: RequestContext) -> ApiKeyOut:
    key = await session.get(ApiKey, key_id)
    if key is None or (key.user_id != actor.id and not is_admin(actor)):
        raise NotFound("API key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        audit.record(
            session,
            ctx,
            "api_key.revoke",
            actor=actor,
            entity_type="api_key",
            entity_id=key.id,
            department_id=key.department_id,
            changes={"name": key.name, "prefix": key.prefix},
        )
        await session.commit()
        await session.refresh(key)
    (out,) = await _out(session, [key])
    return out
