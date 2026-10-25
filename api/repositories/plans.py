import uuid
from typing import Any

import sqlalchemy as sa

from schema import plans, training_contexts


def owns_context(conn: sa.Connection, user_id: uuid.UUID, context_id: uuid.UUID) -> bool:
    return conn.execute(
        sa.select(training_contexts.c.id).where(
            training_contexts.c.id == context_id,
            training_contexts.c.user_id == user_id,
        )
    ).scalar_one_or_none() is not None


def latest(conn: sa.Connection, user_id: uuid.UUID) -> sa.Row[Any] | None:
    return conn.execute(
        sa.select(plans)
        .where(plans.c.user_id == user_id)
        .order_by(plans.c.week_of.desc(), plans.c.generated_at.desc())
        .limit(1)
    ).one_or_none()
