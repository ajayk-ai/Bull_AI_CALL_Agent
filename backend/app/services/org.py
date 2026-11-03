"""Departments and users."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.security import hash_password
from app.models.enums import Role
from app.models.org import Department, User
from app.rbac.permissions import ASSIGNABLE_ROLES, can_see, is_admin, visible_departments
from app.schemas.common import PageParams
from app.schemas.org import DepartmentCreate, DepartmentUpdate, UserCreate, UserUpdate
from app.services import audit
from app.services.auth import find_by_email

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


# ---- users ----


def _check_assignable(actor: User, role: Role, department_id: uuid.UUID | None) -> uuid.UUID | None:
    if role not in ASSIGNABLE_ROLES.get(actor.role, frozenset()):
        raise Forbidden(f"You cannot assign the role {role}")
    if not is_admin(actor):
        if department_id not in (None, actor.department_id):
            raise Forbidden("You can only manage users in your own department")
        department_id = actor.department_id
    if role == Role.ADMIN:
        return None
    if department_id is None:
        raise ValidationFailed("department_id is required for this role")
    return department_id


async def _require_department(session: AsyncSession, department_id: uuid.UUID | None) -> None:
    if department_id is None:
        return
    department = await session.get(Department, department_id)
    if department is None or not department.is_active:
        raise ValidationFailed("Department does not exist or is inactive")


async def list_users(session: AsyncSession, actor: User, params: PageParams) -> tuple[list[User], int]:
    query = select(User)
    if (scope := visible_departments(actor)) is not None:
        query = query.where(User.department_id.in_(scope))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(query.order_by(User.full_name).offset(params.offset).limit(params.page_size))
    return list(rows), total or 0


async def get_user(session: AsyncSession, actor: User, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None or not can_see(actor, user.department_id):
        raise NotFound("User not found")
    return user


async def create_user(session: AsyncSession, actor: User, data: UserCreate, ctx: RequestContext) -> User:
    department_id = _check_assignable(actor, data.role, data.department_id)
    await _require_department(session, department_id)
    if await find_by_email(session, data.email):
        raise Conflict("A user with this email already exists")
    user = User(
        email=data.email.lower(),
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role=data.role,
        department_id=department_id,
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
        changes={"email": user.email, "role": user.role, "department_id": str(department_id)},
    )
    await session.commit()
    return user


async def update_user(
    session: AsyncSession, actor: User, user_id: uuid.UUID, data: UserUpdate, ctx: RequestContext
) -> User:
    user = await get_user(session, actor, user_id)
    if not is_admin(actor) and user.role not in ASSIGNABLE_ROLES[actor.role]:
        raise Forbidden("You cannot edit this user")
    updates = data.model_dump(exclude_unset=True)
    if user.id == actor.id and ("role" in updates or updates.get("is_active") is False):
        raise Forbidden("You cannot change your own role or deactivate yourself")

    if "role" in updates or "department_id" in updates:
        role = updates.get("role", user.role)
        updates["department_id"] = _check_assignable(actor, role, updates.get("department_id", user.department_id))
        await _require_department(session, updates["department_id"])

    before = {k: getattr(user, k) for k in updates}
    for key, value in updates.items():
        setattr(user, key, value)
    if updates.get("is_active") is False or before.get("role", user.role) != user.role:
        user.token_version += 1  # sign the user out
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
    return user


async def reset_password(
    session: AsyncSession, actor: User, user_id: uuid.UUID, new_password: str, ctx: RequestContext
) -> None:
    user = await get_user(session, actor, user_id)
    if not is_admin(actor) and user.role not in ASSIGNABLE_ROLES[actor.role]:
        raise Forbidden("You cannot reset this user's password")
    user.password_hash = hash_password(new_password)
    user.token_version += 1
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
