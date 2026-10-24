"""user profile and training preferences

Revision ID: 0007
Revises: 0006

Two groups of columns with different justifications, kept in one migration because they
are one form on one screen (D29).

`goal`, `experience`, `days_per_week` and `session_minutes` are live engine inputs. The
client has been hardcoding all four; this is where they start being the user's answer.

`birth_year`, `height_cm` and `bodyweight_kg` are collected ahead of anything reading
them — a deliberate call recorded in D29, not an oversight. Nullable, so an account is
usable before intake finishes and a half-filled profile is not a broken row.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    ("birth_year", sa.SmallInteger()),
    ("height_cm", sa.SmallInteger()),
    ("bodyweight_kg", sa.Numeric(5, 2)),
    ("goal", sa.Text()),
    ("experience", sa.Text()),
    ("days_per_week", sa.SmallInteger()),
    ("session_minutes", sa.SmallInteger()),
)

# NULL passes a CHECK in Postgres, which is what lets intake fill these in any order.
# The numeric bounds are typo rails -- they reject a height of 1900cm, they do not
# express an opinion about anyone's body.
CONSTRAINTS = (
    ("ck_users_goal", "goal IN ('strength', 'hypertrophy')"),
    ("ck_users_experience", "experience IN ('beginner', 'intermediate', 'advanced')"),
    ("ck_users_birth_year", "birth_year BETWEEN 1900 AND 2100"),
    ("ck_users_height_cm", "height_cm BETWEEN 50 AND 280"),
    ("ck_users_bodyweight_kg", "bodyweight_kg BETWEEN 20 AND 500"),
    ("ck_users_days_per_week", "days_per_week BETWEEN 1 AND 7"),
    ("ck_users_session_minutes", "session_minutes BETWEEN 10 AND 300"),
)


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.add_column("users", sa.Column(name, type_, nullable=True))
    for name, condition in CONSTRAINTS:
        op.create_check_constraint(name, "users", sa.text(condition))


def downgrade() -> None:
    for name, _ in CONSTRAINTS:
        op.drop_constraint(name, "users", type_="check")
    for name, _ in COLUMNS:
        op.drop_column("users", name)
