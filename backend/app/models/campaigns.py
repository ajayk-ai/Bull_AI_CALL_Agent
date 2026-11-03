import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, str_enum
from app.models.enums import ApprovalDecision, CampaignContactStatus, CampaignStatus, ImportStatus


class Campaign(UUIDPk, Timestamps, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint("max_concurrency BETWEEN 1 AND 100", name="max_concurrency_range"),
        CheckConstraint("max_attempts BETWEEN 1 AND 10", name="max_attempts_range"),
        CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="date_order"),
    )

    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    script_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("script_versions.id"))
    status: Mapped[CampaignStatus] = mapped_column(
        str_enum(CampaignStatus, "campaign_status"), default=CampaignStatus.DRAFT, index=True
    )
    language: Mapped[str | None] = mapped_column(String(16))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    # {"timezone": "Asia/Kolkata", "days": [0..6], "start": "09:30", "end": "18:30"}
    calling_window: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    max_concurrency: Mapped[int] = mapped_column(default=5, server_default=text("5"))
    max_attempts: Mapped[int] = mapped_column(default=3, server_default=text("3"))
    retry_interval_minutes: Mapped[int] = mapped_column(default=60, server_default=text("60"))
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class CampaignContact(UUIDPk, Timestamps, Base):
    __tablename__ = "campaign_contacts"
    __table_args__ = (
        UniqueConstraint("campaign_id", "contact_id"),
        Index("ix_campaign_contacts_due", "status", "next_attempt_at"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"), index=True)
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contacts.id"), index=True)
    status: Mapped[CampaignContactStatus] = mapped_column(
        str_enum(CampaignContactStatus, "campaign_contact_status"), default=CampaignContactStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(64))
    # Per-contact campaign data used by the script, e.g. PO number and original delivery date.
    context: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))


class CampaignImport(UUIDPk, Base):
    """One uploaded contact file, with its validation result. Used for plain contact imports too."""

    __tablename__ = "campaign_imports"

    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    # The uploaded file, encrypted, in object storage.
    object_key: Mapped[str | None] = mapped_column(String(512))
    file_size_bytes: Mapped[int | None]
    headers: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    # Column mapping and options used when the file was processed.
    column_mapping: Mapped[dict | None] = mapped_column(JSONB)
    options: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    new_contacts: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    updated_contacts: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    campaign_contacts: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    status: Mapped[ImportStatus] = mapped_column(str_enum(ImportStatus, "import_status"), default=ImportStatus.UPLOADED)
    total_rows: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    valid_rows: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    error_rows: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    duplicate_rows: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    # [{"row": 5, "field": "phone", "message": "...", "level": "error" | "warning"}]
    errors: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CampaignApproval(UUIDPk, Base):
    __tablename__ = "campaign_approvals"

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"), index=True)
    decision: Mapped[ApprovalDecision] = mapped_column(
        str_enum(ApprovalDecision, "approval_decision"), default=ApprovalDecision.PENDING
    )
    requested_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    comments: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
