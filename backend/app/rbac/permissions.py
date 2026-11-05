"""Role → permission map and department scoping rules.

Admins work across all departments. Users are confined to its own department: requests for
another department's records return 404, so the records' existence is not disclosed.
"""

import uuid
from enum import StrEnum

from app.core.errors import Forbidden, ValidationFailed
from app.models.enums import Role
from app.models.org import User


class Permission(StrEnum):
    DEPARTMENTS_MANAGE = "departments:manage"
    USERS_READ = "users:read"
    USERS_MANAGE = "users:manage"
    CONTACTS_READ = "contacts:read"
    CONTACTS_WRITE = "contacts:write"
    CONTACTS_DELETE = "contacts:delete"
    CONTACTS_VIEW_FULL_NUMBER = "contacts:view_full_number"
    CONSENT_WRITE = "consent:write"
    DNC_READ = "dnc:read"
    DNC_WRITE = "dnc:write"
    DNC_DELETE = "dnc:delete"
    DNC_GLOBAL = "dnc:global"
    AUDIT_READ = "audit:read"
    IMPORTS_WRITE = "imports:write"
    SCRIPTS_READ = "scripts:read"
    SCRIPTS_WRITE = "scripts:write"
    SCRIPTS_APPROVE = "scripts:approve"
    CAMPAIGNS_READ = "campaigns:read"
    CAMPAIGNS_WRITE = "campaigns:write"
    CAMPAIGNS_APPROVE = "campaigns:approve"
    CALLS_READ = "calls:read"
    CALLS_PLACE = "calls:place"


# There are two roles. The admin creates every account and works across all departments. Everyone else
# is a "user" who can do all the calling work of their own department. Approving a script or a campaign
# still needs a second person: the author or submitter cannot approve their own (see services).
_USER = frozenset(
    {
        Permission.CONTACTS_READ,
        Permission.CONTACTS_WRITE,
        Permission.CONTACTS_DELETE,
        Permission.CONTACTS_VIEW_FULL_NUMBER,
        Permission.CONSENT_WRITE,
        Permission.DNC_READ,
        Permission.DNC_WRITE,
        Permission.DNC_DELETE,
        Permission.IMPORTS_WRITE,
        Permission.SCRIPTS_READ,
        Permission.SCRIPTS_WRITE,
        Permission.SCRIPTS_APPROVE,
        Permission.CAMPAIGNS_READ,
        Permission.CAMPAIGNS_WRITE,
        Permission.CAMPAIGNS_APPROVE,
        Permission.CALLS_READ,
        Permission.CALLS_PLACE,
    }
)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.USER: _USER,
    Role.ADMIN: frozenset(Permission),
}


def has_permission(user: User, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[user.role]


def is_admin(user: User) -> bool:
    return user.role == Role.ADMIN


def resolve_department(user: User, requested: uuid.UUID | None) -> uuid.UUID:
    """Department a write applies to. Admins must name one; others always use their own."""
    if is_admin(user):
        if requested is None:
            raise ValidationFailed("department_id is required")
        return requested
    if requested is not None and requested != user.department_id:
        raise Forbidden("You can only act within your own department")
    assert user.department_id is not None  # guaranteed by ck_users_department_required
    return user.department_id


def visible_departments(user: User) -> list[uuid.UUID] | None:
    """Departments the user can read. None means all."""
    if is_admin(user):
        return None
    assert user.department_id is not None
    return [user.department_id]


def can_see(user: User, department_id: uuid.UUID | None) -> bool:
    return is_admin(user) or department_id == user.department_id
