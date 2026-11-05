import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk, str_enum
from app.models.enums import Role


class Department(UUIDPk, Timestamps, Base):
    __tablename__ = "departments"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("uq_users_username_lower", text("lower(username)"), unique=True),
        Index("uq_users_email_lower", text("lower(email)"), unique=True, postgresql_where=text("email IS NOT NULL")),
        CheckConstraint("role = 'admin' OR department_id IS NOT NULL", name="department_required"),
    )

    # The user ID people sign in with. Stored lower-case.
    username: Mapped[str] = mapped_column(String(64))
    # Optional: not everyone has a company e-mail. Also accepted at sign-in.
    email: Mapped[str | None] = mapped_column(String(320))
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(str_enum(Role, "user_role"))
    # Null only for admins, who work across departments.
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # Incremented on password change or deactivation; tokens carrying an older value are rejected.
    token_version: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when an admin chooses the password; the user must pick their own before doing anything else.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

    department: Mapped[Department | None] = relationship(lazy="joined")
