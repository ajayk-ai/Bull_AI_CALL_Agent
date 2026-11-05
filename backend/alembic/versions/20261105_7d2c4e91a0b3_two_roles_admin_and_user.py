"""two roles: admin and user

Revision ID: 7d2c4e91a0b3
Revises: 33a132fd7381
Create Date: 2026-11-05 18:00:00

"""
from typing import Sequence, Union

from alembic import op


revision: str = "7d2c4e91a0b3"
down_revision: Union[str, Sequence[str], None] = "33a132fd7381"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """HOD, campaign manager and operator become one role, "user". Their sessions are ended."""
    op.drop_constraint("user_role", "users", type_="check")
    op.execute(
        "UPDATE users SET role = 'user', token_version = token_version + 1"
        " WHERE role IN ('hod', 'campaign_manager', 'operator')"
    )
    op.create_check_constraint("user_role", "users", "role IN ('admin', 'user')")


def downgrade() -> None:
    """Users become operators, the role with the fewest permissions."""
    op.drop_constraint("user_role", "users", type_="check")
    op.execute("UPDATE users SET role = 'operator', token_version = token_version + 1 WHERE role = 'user'")
    op.create_check_constraint("user_role", "users", "role IN ('admin', 'hod', 'campaign_manager', 'operator')")
