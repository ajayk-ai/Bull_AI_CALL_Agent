"""user id sign-in and forced password change

Revision ID: 33a132fd7381
Revises: e543e3875781
Create Date: 2026-11-05 15:43:54.205200

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '33a132fd7381'
down_revision: Union[str, Sequence[str], None] = 'e543e3875781'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """User IDs for sign-in; e-mail becomes optional; forced password change after an admin sets one."""
    op.add_column("users", sa.Column("username", sa.String(length=64), nullable=True))
    # Existing accounts get a user ID from their e-mail's local part, made unique with part of their id.
    op.execute(
        "UPDATE users SET username = lower(regexp_replace(split_part(email, '@', 1), '[^A-Za-z0-9._-]', '', 'g'))"
        " || '-' || substr(replace(id::text, '-', ''), 25, 8)"
    )
    op.alter_column("users", "username", nullable=False)
    op.add_column(
        "users", sa.Column("must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.alter_column("users", "email", existing_type=sa.VARCHAR(length=320), nullable=True)
    op.drop_index("uq_users_email_lower", table_name="users")
    op.create_index(
        "uq_users_email_lower",
        "users",
        [sa.literal_column("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index("uq_users_username_lower", "users", [sa.literal_column("lower(username)")], unique=True)


def downgrade() -> None:
    op.drop_index("uq_users_username_lower", table_name="users")
    op.drop_index("uq_users_email_lower", table_name="users")
    # Accounts without an e-mail cannot be represented before this revision.
    op.execute("UPDATE users SET email = username || '@no-email.invalid' WHERE email IS NULL")
    op.create_index("uq_users_email_lower", "users", [sa.literal_column("lower(email)")], unique=True)
    op.alter_column("users", "email", existing_type=sa.VARCHAR(length=320), nullable=False)
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "username")
