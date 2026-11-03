"""Login, token refresh and password change."""

import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.errors import TooManyRequests, Unauthorized, ValidationFailed
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.models.org import User
from app.schemas.org import TokenResponse
from app.services import audit

MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 15 * 60

# Verified against when the e-mail is unknown, so a missing account takes as long as a wrong password.
_DUMMY_HASH = hash_password("not-a-real-password-0000")


def _fail_key(email: str) -> str:
    return f"auth:failed:{email.lower()}"


def issue_tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_token(user.id, user.token_version, "access"),
        refresh_token=create_token(user.id, user.token_version, "refresh"),
        expires_in=get_settings().access_token_minutes * 60,
    )


async def find_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(func.lower(User.email) == email.lower()))


async def login(session: AsyncSession, redis: Redis, email: str, password: str, ctx: RequestContext) -> TokenResponse:
    key = _fail_key(email)
    if int(await redis.get(key) or 0) >= MAX_FAILED_LOGINS:
        raise TooManyRequests("Too many failed attempts. Try again in 15 minutes.")

    user = await find_by_email(session, email)
    valid = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    if not (user and valid and user.is_active):
        failures = await redis.incr(key)
        if failures == 1:
            await redis.expire(key, LOCKOUT_SECONDS)
        reason = "unknown_email" if not user else ("inactive" if valid else "wrong_password")
        audit.record(
            session,
            ctx,
            "auth.login_failed",
            actor_email=email,
            entity_type="user",
            entity_id=user.id if user else None,
            department_id=user.department_id if user else None,
            changes={"reason": reason},
        )
        await session.commit()
        raise Unauthorized("Invalid email or password")

    await redis.delete(key)
    user.last_login_at = datetime.now(UTC)
    audit.record(
        session, ctx, "auth.login", actor=user, entity_type="user", entity_id=user.id, department_id=user.department_id
    )
    await session.commit()
    return issue_tokens(user)


async def refresh(session: AsyncSession, refresh_token: str) -> TokenResponse:
    payload = decode_token(refresh_token, "refresh")
    user = await session.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active or user.token_version != payload["ver"]:
        raise Unauthorized("Session is no longer valid")
    return issue_tokens(user)


async def change_password(
    session: AsyncSession, user: User, current: str, new: str, ctx: RequestContext
) -> TokenResponse:
    if not verify_password(current, user.password_hash):
        raise ValidationFailed("Current password is incorrect")
    if current == new:
        raise ValidationFailed("New password must differ from the current one")
    user.password_hash = hash_password(new)
    user.token_version += 1  # signs out every other session
    audit.record(
        session,
        ctx,
        "auth.password_changed",
        actor=user,
        entity_type="user",
        entity_id=user.id,
        department_id=user.department_id,
    )
    await session.commit()
    return issue_tokens(user)
