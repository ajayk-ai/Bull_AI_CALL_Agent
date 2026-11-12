import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AliasChoices, BaseModel, EmailStr, Field, StringConstraints

from app.models.enums import Role
from app.schemas.common import Name, ORMModel, Password

DepartmentCode = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z0-9_]{2,32}$")
]


# The user ID people sign in with: letters, digits, dot, dash, underscore. Stored lower-case.
UserId = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
]


class LoginRequest(BaseModel):
    # User ID or e-mail. ("email" is still accepted as the field name.)
    login: str = Field(validation_alias=AliasChoices("login", "username", "email"), min_length=1, max_length=320)
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105  (OAuth2 token type, not a secret)
    expires_in: int


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: Password


class DepartmentCreate(BaseModel):
    code: DepartmentCode
    name: Name


class DepartmentUpdate(BaseModel):
    name: Name | None = None
    is_active: bool | None = None


class DepartmentOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    username: UserId
    full_name: Name
    email: EmailStr | None = None
    role: Role
    department_id: uuid.UUID | None = None
    # Leave empty to have a password generated. Either way it is shown once and must be changed at first sign-in.
    password: Password | None = None


class UserUpdate(BaseModel):
    full_name: Name | None = None
    email: EmailStr | None = None
    role: Role | None = None
    department_id: uuid.UUID | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    # Leave empty to have one generated.
    new_password: Password | None = None


class UserOut(ORMModel):
    id: uuid.UUID
    username: str
    email: str | None
    full_name: str
    role: Role
    department_id: uuid.UUID | None
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime
    # Locked after repeated failed sign-ins (clears by itself after 15 minutes, or an admin unlocks it).
    locked: bool = False


class UserCredentials(BaseModel):
    """Returned once, when an admin creates an account or resets a password. Never stored in clear text."""

    user: UserOut
    temporary_password: str


class MeOut(UserOut):
    permissions: list[str]
    # Whether scripts and campaigns need a second person to approve them.
    second_approver_required: bool = True
