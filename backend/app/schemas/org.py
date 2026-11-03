import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, StringConstraints

from app.models.enums import Role
from app.schemas.common import Name, ORMModel, Password

DepartmentCode = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z0-9_]{2,32}$")
]


class LoginRequest(BaseModel):
    email: EmailStr
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
    email: EmailStr
    full_name: Name
    password: Password
    role: Role
    department_id: uuid.UUID | None = None


class UserUpdate(BaseModel):
    full_name: Name | None = None
    role: Role | None = None
    department_id: uuid.UUID | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    new_password: Password


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    department_id: uuid.UUID | None
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class MeOut(UserOut):
    permissions: list[str]
