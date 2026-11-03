import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, str_enum
from app.models.enums import ExtractionStatus, FollowupStatus


class ExtractedResult(UUIDPk, Timestamps, Base):
    """Model output, schema-validated output and human corrections are kept in separate columns."""

    __tablename__ = "extracted_results"

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), index=True)
    script_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("script_versions.id"))
    model: Mapped[str] = mapped_column(String(100))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    validated: Mapped[dict | None] = mapped_column(JSONB)
    corrected: Mapped[dict | None] = mapped_column(JSONB)
    validation_errors: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    status: Mapped[ExtractionStatus] = mapped_column(
        str_enum(ExtractionStatus, "extraction_status"), default=ExtractionStatus.PENDING, index=True
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[str | None] = mapped_column(Text)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExtractionFieldEvidence(UUIDPk, Base):
    __tablename__ = "extraction_field_evidence"

    extracted_result_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extracted_results.id"), index=True)
    field_path: Mapped[str] = mapped_column(String(200))
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(Float)
    transcript_turn_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    quote: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FollowupTask(UUIDPk, Timestamps, Base):
    __tablename__ = "followup_tasks"

    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calls.id"), index=True)
    extracted_result_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("extracted_results.id"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id"))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[FollowupStatus] = mapped_column(
        str_enum(FollowupStatus, "followup_status"), default=FollowupStatus.OPEN, index=True
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
