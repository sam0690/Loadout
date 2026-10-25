"""The event log. Append-only: there is no UPDATE or DELETE here, and there must not be."""

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from schema import events


def append(conn: sa.Connection, rows: list[dict[str, Any]]) -> int:
    """Insert, skipping ids already stored (constraint 3). Returns how many landed."""
    # RETURNING rather than rowcount: a multi-values INSERT reports -1, and the
    # count of rows that actually landed is the whole signal a client needs to know
    # its retry was absorbed.
    return len(
        conn.execute(
            insert(events)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(events.c.id)
        ).all()
    )


def for_user(conn: sa.Connection, user_id: uuid.UUID) -> list[sa.Row[Any]]:
    return list(
        conn.execute(
            sa.select(events)
            .where(events.c.user_id == user_id)
            .order_by(events.c.client_ts, events.c.id)
        ).all()
    )
