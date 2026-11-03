import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, str_enum
from app.models.enums import ScriptVersionStatus


class Script(UUIDPk, Timestamps, Base):
    __tablename__ = "scripts"

    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class ScriptVersion(UUIDPk, Timestamps, Base):
    """Immutable once published. Campaigns and calls reference a version, never the script."""

    __tablename__ = "script_versions"
    __table_args__ = (UniqueConstraint("script_id", "version_no"),)

    script_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scripts.id"), index=True)
    version_no: Mapped[int]
    status: Mapped[ScriptVersionStatus] = mapped_column(
        str_enum(ScriptVersionStatus, "script_version_status"), default=ScriptVersionStatus.DRAFT
    )
    # Objective, agent identity, instructions, languages, voice, questions, rules, limits, closing,
    # escalation. Shape is defined by the Phase 2 script builder schema.
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    extraction_schema: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
