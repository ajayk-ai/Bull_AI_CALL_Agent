"""Departments and users."""

import secrets
import uuid

from redis.asyncio import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.redis import get_redis
from app.core.security import hash_password
from app.models.enums import Role
from app.models.org import Department, User
from app.rbac.permissions import can_see, visible_departments
from app.schemas.common import PageParams
from app.schemas.org import DepartmentCreate, DepartmentUpdate, UserCreate, UserCredentials, UserOut, UserUpdate
from app.services import audit, auth

# ---- departments ----


async def list_departments(session: AsyncSession, actor: User) -> list[Department]:
    query = select(Department).order_by(Department.name)
    if (scope := visible_departments(actor)) is not None:
        query = query.where(Department.id.in_(scope))
    return list(await session.scalars(query))


async def get_department(session: AsyncSession, actor: User, department_id: uuid.UUID) -> Department:
    department = await session.get(Department, department_id)
    if department is None or not can_see(actor, department.id):
        raise NotFound("Department not found")
    return department


async def create_department(
    session: AsyncSession, actor: User, data: DepartmentCreate, ctx: RequestContext
) -> Department:
    if await session.scalar(select(Department.id).where(Department.code == data.code)):
        raise Conflict(f"Department code {data.code} already exists")
    department = Department(code=data.code, name=data.name)
    session.add(department)
    await session.flush()
    audit.record(
        session,
        ctx,
        "department.create",
        actor=actor,
        entity_type="department",
        entity_id=department.id,
        department_id=department.id,
        changes=data.model_dump(),
    )
    await session.commit()
    return department


async def update_department(
    session: AsyncSession, actor: User, department_id: uuid.UUID, data: DepartmentUpdate, ctx: RequestContext
) -> Department:
    department = await get_department(session, actor, department_id)
    updates = data.model_dump(exclude_unset=True)
    changes = audit.diff({k: getattr(department, k) for k in updates}, updates)
    for key, value in updates.items():
        setattr(department, key, value)
    audit.record(
        session,
        ctx,
        "department.update",
        actor=actor,
        entity_type="department",
        entity_id=department.id,
        department_id=department.id,
        changes=changes,
    )
    await session.commit()
    return department


# ---- users (admin only; enforced by the users:manage permission) ----

# No look-alike characters (0/O, 1/l/I), so a temporary password can be read out or typed without mistakes.
_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"  # noqa: S105  (character set, not a password)


def generate_password(length: int = 12) -> str:
    while True:
        password = "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))
        if (
            any(c.isupper() for c in password)
            and any(c.islower() for c in password)
            and any(c.isdigit() for c in password)
        ):
            return password


async def _department_for(session: AsyncSession, role: Role, department_id: uuid.UUID | None) -> uuid.UUID | None:
    if role == Role.ADMIN:
        return None  # admins work across all departments
    if department_id is None:
        raise ValidationFailed("Choose a department for this role")
    department = await session.get(Department, department_id)
    if department is None or not department.is_active:
        raise ValidationFailed("Department does not exist or is inactive")
    return department_id


async def _out(redis: Redis, users: list[User]) -> list[UserOut]:
    if not users:
        return []
    counts = await redis.mget([auth.fail_key(u, "") for u in users])
    return [
        UserOut.model_validate(u).model_copy(update={"locked": int(c or 0) >= auth.MAX_FAILED_LOGINS})
        for u, c in zip(users, counts, strict=True)
    ]


async def _active_admins(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).where(User.role == Role.ADMIN, User.is_active.is_(True))) or 0


async def list_users(
    session: AsyncSession,
    actor: User,
    params: PageParams,
    search: str | None = None,
    department_id: uuid.UUID | None = None,
    role: Role | None = None,
    is_active: bool | None = None,
) -> tuple[list[UserOut], int]:
    query = select(User)
    if (scope := visible_departments(actor)) is not None:
        query = query.where(User.department_id.in_(scope))
    if search:
        like = f"%{search.strip()}%"
        query = query.where(or_(User.username.ilike(like), User.full_name.ilike(like), User.email.ilike(like)))
    for column, value in ((User.department_id, department_id), (User.role, role), (User.is_active, is_active)):
        if value is not None:
            query = query.where(column == value)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = list(await session.scalars(query.order_by(User.full_name).offset(params.offset).limit(params.page_size)))
    return await _out(get_redis(), rows), total or 0


async def _get(session: AsyncSession, actor: User, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None or not can_see(actor, user.department_id):
        raise NotFound("User not found")
    return user


async def get_user(session: AsyncSession, actor: User, user_id: uuid.UUID) -> UserOut:
    return (await _out(get_redis(), [await _get(session, actor, user_id)]))[0]


async def _check_unique(session: AsyncSession, username: str | None, email: str | None, exclude: uuid.UUID | None):
    if username and (other := await auth.find_by_username(session, username)) and other.id != exclude:
        raise Conflict(f"The user ID {username} is already taken")
    if email and (other := await auth.find_by_email(session, email)) and other.id != exclude:
        raise Conflict("Another account already uses this e-mail")


async def create_user(session: AsyncSession, actor: User, data: UserCreate, ctx: RequestContext) -> UserCredentials:
    department_id = await _department_for(session, data.role, data.department_id)
    await _check_unique(session, data.username, data.email, None)
    password = data.password or generate_password()
    user = User(
        username=data.username,
        email=data.email.lower() if data.email else None,
        full_name=data.full_name,
        password_hash=hash_password(password),
        role=data.role,
        department_id=department_id,
        must_change_password=True,
    )
    session.add(user)
    await session.flush()
    audit.record(
        session,
        ctx,
        "user.create",
        actor=actor,
        entity_type="user",
        entity_id=user.id,
        department_id=department_id,
        changes={"username": user.username, "email": user.email, "role": user.role, "department_id": department_id},
    )
    await session.commit()
    return UserCredentials(user=(await _out(get_redis(), [user]))[0], temporary_password=password)


async def update_user(
    session: AsyncSession, actor: User, user_id: uuid.UUID, data: UserUpdate, ctx: RequestContext
) -> UserOut:
    user = await _get(session, actor, user_id)
    updates = data.model_dump(exclude_unset=True)
    if user.id == actor.id and ("role" in updates or updates.get("is_active") is False):
        raise Forbidden("You cannot change your own role or deactivate yourself")
    role = updates.get("role", user.role)
    removing_admin = (
        user.role == Role.ADMIN and user.is_active and (role != Role.ADMIN or updates.get("is_active") is False)
    )
    if removing_admin and await _active_admins(session) <= 1:
        raise Conflict("This is the last active admin; make another admin first")
    if "role" in updates or "department_id" in updates:
        updates["department_id"] = await _department_for(
            session, role, updates.get("department_id", user.department_id)
        )
    if updates.get("email"):
        updates["email"] = updates["email"].lower()
        await _check_unique(session, None, updates["email"], user.id)

    before = {k: getattr(user, k) for k in updates}
    for key, value in updates.items():
        setattr(user, key, value)
    if updates.get("is_active") is False or before.get("role", user.role) != user.role:
        user.token_version += 1  # signs the user out
    audit.record(
        session,
        ctx,
        "user.update",
        actor=actor,
        entity_type="user",
        entity_id=user.id,
        department_id=user.department_id,
        changes=audit.diff(before, updates),
    )
    await session.commit()
    return (await _out(get_redis(), [user]))[0]


async def reset_password(
    session: AsyncSession, actor: User, user_id: uuid.UUID, new_password: str | None, ctx: RequestContext
) -> UserCredentials:
    user = await _get(session, actor, user_id)
    password = new_password or generate_password()
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.token_version += 1  # signs the user out everywhere
    await get_redis().delete(auth.fail_key(user, ""))
    audit.record(
        session,
        ctx,
        "user.password_reset",
        actor=actor,
        entity_type="user",
        entity_id=user.id,
        department_id=user.department_id,
    )
    await session.commit()
    return UserCredentials(user=(await _out(get_redis(), [user]))[0], temporary_password=password)


async def unlock(session: AsyncSession, actor: User, user_id: uuid.UUID, ctx: RequestContext) -> UserOut:
    """Clears the lock after repeated failed sign-ins."""
    user = await _get(session, actor, user_id)
    await get_redis().delete(auth.fail_key(user, ""))
    audit.record(
        session,
        ctx,
        "user.unlock",
        actor=actor,
        entity_type="user",
        entity_id=user.id,
        department_id=user.department_id,
    )
    await session.commit()
    return (await _out(get_redis(), [user]))[0]
