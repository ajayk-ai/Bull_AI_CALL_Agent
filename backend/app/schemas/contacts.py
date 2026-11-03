import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.models.enums import ConsentStatus, ConsentType
from app.schemas.common import LanguageCode, Name, ORMModel

PhoneInput = Annotated[str, StringConstraints(strip_whitespace=True, min_length=6, max_length=32)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
CustomValue = str | int | float | bool | None


def _check_custom_fields(value: dict[str, CustomValue] | None) -> dict[str, CustomValue] | None:
    if value is None:
        return value
    if len(value) > 50:
        raise ValueError("at most 50 custom fields")
    for key, item in value.items():
        if not 1 <= len(key) <= 64:
            raise ValueError("custom field names must be 1 to 64 characters")
        if isinstance(item, str) and len(item) > 1000:
            raise ValueError(f"custom field {key!r} is longer than 1000 characters")
    return value


class ContactCreate(BaseModel):
    department_id: uuid.UUID | None = None
    name: Name
    phone: PhoneInput
    company: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    language: LanguageCode | None = None
    custom_fields: dict[str, CustomValue] = Field(default_factory=dict)

    _custom = field_validator("custom_fields")(_check_custom_fields)


class ContactUpdate(BaseModel):
    name: Name | None = None
    phone: PhoneInput | None = None
    company: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    language: LanguageCode | None = None
    custom_fields: dict[str, CustomValue] | None = None

    _custom = field_validator("custom_fields")(_check_custom_fields)


class ContactOut(ORMModel):
    id: uuid.UUID
    department_id: uuid.UUID
    name: str
    company: str | None
    phone_masked: str
    language: str | None
    custom_fields: dict
    do_not_call: bool = False
    created_at: datetime
    updated_at: datetime


class ContactPhoneOut(BaseModel):
    id: uuid.UUID
    phone: str


class ConsentCreate(BaseModel):
    consent_type: ConsentType
    status: ConsentStatus
    source: Short
    notes: Annotated[str, StringConstraints(max_length=2000)] | None = None
    captured_at: datetime | None = None


class ConsentOut(ORMModel):
    id: uuid.UUID
    contact_id: uuid.UUID
    consent_type: ConsentType
    status: ConsentStatus
    source: str
    notes: str | None
    captured_at: datetime
    captured_by_id: uuid.UUID | None


class DncCreate(BaseModel):
    phone: PhoneInput
    # Omit to use your own department. Admins may set `global_scope` to suppress for every department.
    department_id: uuid.UUID | None = None
    global_scope: bool = False
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    source: Short = "manual"
    expires_at: datetime | None = None


class DncOut(ORMModel):
    id: uuid.UUID
    phone_masked: str
    department_id: uuid.UUID | None
    reason: str
    source: str
    expires_at: datetime | None
    added_by_id: uuid.UUID | None
    created_at: datetime
