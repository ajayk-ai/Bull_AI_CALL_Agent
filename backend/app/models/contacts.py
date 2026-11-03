import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, str_enum
from app.models.enums import ConsentStatus, ConsentType


class Contact(UUIDPk, Timestamps, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        # One live contact per number per department; deleted contacts keep their history.
        Index(
            "uq_contacts_department_phone_live",
            "department_id",
            "phone_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(200))
    phone_encrypted: Mapped[str] = mapped_column(Text)
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    phone_masked: Mapped[str] = mapped_column(String(32))
    language: Mapped[str | None] = mapped_column(String(16))  # BCP-47, e.g. ta-IN
    custom_fields: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConsentRecord(UUIDPk, Base):
    """Append-only: a change of consent is a new row, so the history is kept as evidence."""

    __tablename__ = "consent_records"

    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contacts.id"), index=True)
    consent_type: Mapped[ConsentType] = mapped_column(str_enum(ConsentType, "consent_type"))
    status: Mapped[ConsentStatus] = mapped_column(str_enum(ConsentStatus, "consent_status"))
    source: Mapped[str] = mapped_column(String(100))  # e.g. "supplier agreement", "call", "email"
    notes: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    captured_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DoNotCall(UUIDPk, Base):
    """A suppressed number. department_id NULL means suppressed for every department."""

    __tablename__ = "do_not_call"
    __table_args__ = (UniqueConstraint("phone_hash", "department_id", postgresql_nulls_not_distinct=True),)

    phone_encrypted: Mapped[str] = mapped_column(Text)
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    phone_masked: Mapped[str] = mapped_column(String(32))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"), index=True)
    reason: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(100))  # e.g. "caller request", "manual", "import"
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
