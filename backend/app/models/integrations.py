import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, str_enum
from app.models.enums import ProviderKind


class VoiceProviderAccount(UUIDPk, Timestamps, Base):
    """A telephony or AI provider account. department_id NULL means available to every department."""

    __tablename__ = "voice_provider_accounts"
    __table_args__ = (UniqueConstraint("kind", "provider", "name"),)

    kind: Mapped[ProviderKind] = mapped_column(str_enum(ProviderKind, "provider_kind"))
    provider: Mapped[str] = mapped_column(String(32))  # e.g. "frejun", "exotel", "gemini", "mock"
    name: Mapped[str] = mapped_column(String(100))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"), index=True)
    # Encrypted JSON. Credentials may also come from environment variables, in which case this is NULL.
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class IntegrationConfig(UUIDPk, Timestamps, Base):
    __tablename__ = "integration_configs"
    __table_args__ = (UniqueConstraint("key", "department_id", postgresql_nulls_not_distinct=True),)

    key: Mapped[str] = mapped_column(String(100))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    secrets_encrypted: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class ApiKey(UUIDPk, Timestamps, Base):
    """A key another system (or an AI assistant over MCP) uses to call this platform. It acts as the user who
    created it, limited to `access`; only a SHA-256 of the key is stored."""

    __tablename__ = "api_keys"

    name: Mapped[str] = mapped_column(String(100))
    # Shown in lists so people can tell keys apart, e.g. "bmk_3fa9c1d2".
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"), index=True)
    access: Mapped[str] = mapped_column(String(16))  # "read" | "write"
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
