import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, str_enum
from app.models.enums import CallStatus, QueueStatus


class CallQueueItem(UUIDPk, Base):
    """Durable record of a scheduled dial. Redis holds the live queue; this table survives restarts."""

    __tablename__ = "call_queue"
    __table_args__ = (Index("ix_call_queue_due", "status", "scheduled_at"),)

    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id"), index=True)
    campaign_contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaign_contacts.id"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id"))
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    attempt_no: Mapped[int] = mapped_column(default=1, server_default=text("1"))
    priority: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[QueueStatus] = mapped_column(str_enum(QueueStatus, "queue_status"), default=QueueStatus.WAITING)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Call(UUIDPk, Timestamps, Base):
    __tablename__ = "calls"
    __table_args__ = (
        UniqueConstraint("provider", "provider_call_id"),
        Index("ix_calls_department_created", "department_id", "created_at"),
    )

    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"))
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id"), index=True)
    campaign_contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaign_contacts.id"), index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id"), index=True)
    initiated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    phone_encrypted: Mapped[str] = mapped_column(Text)
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    phone_masked: Mapped[str] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(16), default="outbound", server_default=text("'outbound'"))
    attempt_no: Mapped[int] = mapped_column(default=1, server_default=text("1"))
    # Exact script version and AI configuration (engine, models, voice, language, VAD) used for this call.
    script_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("script_versions.id"))
    ai_config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    provider: Mapped[str] = mapped_column(String(32))
    provider_call_id: Mapped[str | None] = mapped_column(String(128))
    # True for mock-telephony calls. Simulated calls are never reported as real results.
    is_simulated: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[CallStatus] = mapped_column(
        str_enum(CallStatus, "call_status"), default=CallStatus.QUEUED, index=True
    )
    outcome: Mapped[str | None] = mapped_column(String(64))
    outcome_note: Mapped[str | None] = mapped_column(Text)
    # How the call ended: agent_end_call, caller_hangup, silence, time_limit, no_answer, ...
    end_reason: Mapped[str | None] = mapped_column(String(32))
    # Data the script uses for this call, e.g. {"items": [{"po_number": ...}]}.
    context: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    # Latency, interruptions, audio seconds, turns.
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    # Answers recorded during the call through the scenario graph (app/voice/scenario.py), per line.
    answers: Mapped[dict | None] = mapped_column(JSONB)
    language_detected: Mapped[str | None] = mapped_column(String(16))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(Text)


class CallEvent(UUIDPk, Base):
    """Provider webhook and internal lifecycle events. The unique key makes webhook handling idempotent."""

    __tablename__ = "call_events"
    __table_args__ = (UniqueConstraint("provider", "provider_event_id"),)

    call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calls.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_event_id: Mapped[str] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Transcript(UUIDPk, Base):
    """The original transcript, in the language spoken. Never edited; corrections go to extracted_results."""

    __tablename__ = "transcripts"

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), unique=True)
    # [{"turn_id", "speaker", "text", "language", "start_ms", "end_ms"}]
    turns: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    languages: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Recording(UUIDPk, Base):
    """Pointer to an audio file in object storage. The audio itself is never stored in PostgreSQL."""

    __tablename__ = "recordings"

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), index=True)
    bucket: Mapped[str] = mapped_column(String(100))
    object_key: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(64))
    duration_seconds: Mapped[int | None]
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
