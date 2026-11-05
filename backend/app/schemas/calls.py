import uuid
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator

from app.models.enums import CallStatus
from app.schemas.common import LanguageCode, Name, ORMModel
from app.schemas.contacts import PhoneInput


class CallCreate(BaseModel):
    """Call an existing contact, or a number typed in by hand."""

    contact_id: uuid.UUID | None = None
    phone: PhoneInput | None = None
    name: Name | None = Field(None, description="Who is being called, when calling a number by hand")
    company: str | None = Field(None, max_length=200)
    department_id: uuid.UUID | None = None
    script_version_id: uuid.UUID
    language: LanguageCode | None = None
    # Data the script needs for this call, e.g. {"items": [{"po_number": "450001", ...}]}.
    context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        if (self.contact_id is None) == (self.phone is None):
            raise ValueError("give either contact_id or phone")
        return self


class CallOut(ORMModel):
    id: uuid.UUID
    department_id: uuid.UUID
    campaign_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    initiated_by_id: uuid.UUID | None
    phone_masked: str
    script_version_id: uuid.UUID
    provider: str
    is_simulated: bool
    status: CallStatus
    outcome: str | None
    outcome_note: str | None
    end_reason: str | None
    language_detected: str | None
    attempt_no: int
    started_at: datetime | None
    answered_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int | None
    error: str | None
    created_at: datetime
    contact_name: str | None = None


class CallEventOut(ORMModel):
    event_type: str
    payload: dict
    received_at: datetime


class RecordingOut(ORMModel):
    id: uuid.UUID
    bucket: str
    content_type: str
    duration_seconds: int | None
    created_at: datetime


class CallDetail(CallOut):
    ai_config: dict
    context: dict
    metrics: dict
    transcript: list[dict] = []
    events: list[CallEventOut] = []
    recordings: list[RecordingOut] = []
