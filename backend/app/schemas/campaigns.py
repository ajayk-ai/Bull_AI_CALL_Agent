import uuid
from datetime import date, datetime, time
from typing import Annotated, Any, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.core.config import get_settings
from app.models.enums import ApprovalDecision, CampaignContactStatus, CampaignStatus
from app.schemas.common import LanguageCode, Name, ORMModel

Description = Annotated[str, StringConstraints(max_length=2000)]


class CallingWindow(BaseModel):
    """When calls may be placed. Days: 0 = Monday ... 6 = Sunday.

    The default (Mon-Sat, 09:30-18:30 IST) is a proposal pending confirmation by the compliance team.
    """

    timezone: str = "Asia/Kolkata"
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5], min_length=1, max_length=7)
    start: time = time(9, 30)
    end: time = time(18, 30)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError, ValueError:
            raise ValueError(f"unknown time zone {value!r}")
        return value

    @field_validator("days")
    @classmethod
    def _days(cls, value: list[int]) -> list[int]:
        if any(d not in range(7) for d in value) or len(set(value)) != len(value):
            raise ValueError("days must be distinct numbers from 0 (Monday) to 6 (Sunday)")
        return sorted(value)

    @model_validator(mode="after")
    def _order(self) -> Self:
        if self.start >= self.end:
            raise ValueError("start must be before end")
        return self


def _max_concurrency(value: int | None) -> int | None:
    limit = get_settings().max_concurrent_calls
    if value is not None and not 1 <= value <= limit:
        raise ValueError(f"must be between 1 and the platform limit of {limit}")
    return value


class _CampaignFields(BaseModel):
    description: Description | None = None
    owner_id: uuid.UUID | None = None
    script_version_id: uuid.UUID | None = None
    language: LanguageCode | None = None
    start_date: date | None = None
    end_date: date | None = None
    calling_window: CallingWindow | None = None
    max_concurrency: int | None = None
    max_attempts: int | None = Field(None, ge=1, le=10)
    retry_interval_minutes: int | None = Field(None, ge=5, le=1440)

    @field_validator("max_concurrency")
    @classmethod
    def _concurrency(cls, value: int | None) -> int | None:
        return _max_concurrency(value)

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class CampaignCreate(_CampaignFields):
    department_id: uuid.UUID | None = None
    name: Name


class CampaignUpdate(_CampaignFields):
    name: Name | None = None


class CampaignOut(ORMModel):
    id: uuid.UUID
    department_id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID
    script_version_id: uuid.UUID | None
    status: CampaignStatus
    language: str | None
    start_date: date | None
    end_date: date | None
    calling_window: dict
    max_concurrency: int
    max_attempts: int
    retry_interval_minutes: int
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    contact_count: int = 0


class ApprovalOut(ORMModel):
    id: uuid.UUID
    decision: ApprovalDecision
    requested_by_id: uuid.UUID
    decided_by_id: uuid.UUID | None
    comments: str | None
    requested_at: datetime
    decided_at: datetime | None


class CampaignContactsAdd(BaseModel):
    contact_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    # Campaign data for each contact, e.g. {"items": [{"po_number": "450001", ...}]}. Applied to every contact listed.
    context: dict[str, Any] = Field(default_factory=dict)


class CampaignContactOut(ORMModel):
    id: uuid.UUID
    contact_id: uuid.UUID
    contact_name: str
    company: str | None
    phone_masked: str
    do_not_call: bool
    status: CampaignContactStatus
    attempts: int
    outcome: str | None
    context: dict
    created_at: datetime
