import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.common import ORMModel

KeyAccess = Literal["read", "write"]


class ApiKeyCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    access: KeyAccess = "read"
    # None: never expires.
    expires_in_days: int | None = Field(90, ge=1, le=730)


class ApiKeyOut(ORMModel):
    id: uuid.UUID
    name: str
    prefix: str
    access: KeyAccess
    user_id: uuid.UUID
    user_name: str | None = None
    department_id: uuid.UUID | None
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    # The full key. Returned once, at creation; only its hash is stored.
    key: str
