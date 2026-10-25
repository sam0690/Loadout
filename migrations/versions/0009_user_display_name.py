"""a display name for the profile

Revision ID: 0009
Revises: 0008

Nullable: an account has no name until its owner gives one, and the app falls back to
the email.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0009'
down_revision: str | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_users_display_name", "users", "char_length(display_name) BETWEEN 1 AND 40"
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_display_name", "users")
    op.drop_column("users", "display_name")
