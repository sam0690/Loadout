import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from ingest.equipment import resolve_slug
from schema import equipment, gym_archetypes, training_context_loads, training_contexts

CONTEXT_LOADS = (
    Path(__file__).resolve().parent.parent.parent / "queries" / "context_loads.sql"
).read_text()


def equipment_id(conn: sa.Connection, raw: str) -> uuid.UUID:
    """Slug or brand alias to canonical id. Raises UnknownEquipment for anything else.

    Reuses 0.2's resolver so the API and the ingest cannot drift on what a name means.
    """
    found: uuid.UUID = conn.execute(
        sa.select(equipment.c.id).where(equipment.c.slug == resolve_slug(conn, raw))
    ).scalar_one()
    return found


def archetype_id(conn: sa.Connection, slug: str) -> uuid.UUID | None:
    found: uuid.UUID | None = conn.execute(
        sa.select(gym_archetypes.c.id).where(gym_archetypes.c.slug == slug)
    ).scalar_one_or_none()
    return found


def archetype_slug(conn: sa.Connection, archetype_id: uuid.UUID) -> str | None:
    found: str | None = conn.execute(
        sa.select(gym_archetypes.c.slug).where(gym_archetypes.c.id == archetype_id)
    ).scalar_one_or_none()
    return found


def archetypes(conn: sa.Connection) -> list[sa.Row[Any]]:
    """Ordered by size, so the leanest kit reads first."""
    return list(
        conn.execute(
            sa.select(gym_archetypes).order_by(
                sa.func.cardinality(gym_archetypes.c.equipment_ids), gym_archetypes.c.name
            )
        ).all()
    )


def equipment_slugs(conn: sa.Connection) -> dict[uuid.UUID, str]:
    return {r.id: r.slug for r in conn.execute(sa.select(equipment.c.id, equipment.c.slug))}


def resolved_equipment(conn: sa.Connection, context_id: uuid.UUID) -> list[sa.Row[Any]]:
    return list(
        conn.execute(sa.text(CONTEXT_LOADS), {"training_context_id": context_id}).all()
    )


def owned(conn: sa.Connection, context_id: uuid.UUID, user_id: uuid.UUID) -> sa.Row[Any] | None:
    return conn.execute(
        sa.select(training_contexts).where(
            training_contexts.c.id == context_id,
            # Ownership is part of the lookup, not a check after it.
            training_contexts.c.user_id == user_id,
        )
    ).one_or_none()


def for_user(conn: sa.Connection, user_id: uuid.UUID) -> list[sa.Row[Any]]:
    return list(
        conn.execute(
            sa.select(training_contexts)
            .where(training_contexts.c.user_id == user_id)
            .order_by(training_contexts.c.is_default.desc(), training_contexts.c.label)
        ).all()
    )


def count_for_user(conn: sa.Connection, user_id: uuid.UUID) -> int:
    count: int = conn.execute(
        sa.select(sa.func.count())
        .select_from(training_contexts)
        .where(training_contexts.c.user_id == user_id)
    ).scalar_one()
    return count


def clear_other_defaults(
    conn: sa.Connection, user_id: uuid.UUID, keep: uuid.UUID | None
) -> None:
    """The database allows one default per user, so demote the old one first."""
    stmt = sa.update(training_contexts).where(
        training_contexts.c.user_id == user_id, training_contexts.c.is_default.is_(True)
    )
    if keep is not None:
        stmt = stmt.where(training_contexts.c.id != keep)
    conn.execute(stmt.values(is_default=False))


def insert_context(conn: sa.Connection, values: dict[str, Any]) -> None:
    conn.execute(sa.insert(training_contexts).values(**values))


def update_context(conn: sa.Connection, context_id: uuid.UUID, values: dict[str, Any]) -> None:
    conn.execute(
        sa.update(training_contexts).where(training_contexts.c.id == context_id).values(**values)
    )


def delete_context(conn: sa.Connection, context_id: uuid.UUID) -> None:
    conn.execute(sa.delete(training_contexts).where(training_contexts.c.id == context_id))


def first_by_label(conn: sa.Connection, user_id: uuid.UUID) -> uuid.UUID | None:
    found: uuid.UUID | None = conn.execute(
        sa.select(training_contexts.c.id)
        .where(training_contexts.c.user_id == user_id)
        .order_by(training_contexts.c.label)
        .limit(1)
    ).scalar_one_or_none()
    return found


def make_default(conn: sa.Connection, context_id: uuid.UUID) -> None:
    update_context(conn, context_id, {"is_default": True})


def delete_loads(conn: sa.Connection, context_id: uuid.UUID) -> None:
    conn.execute(
        sa.delete(training_context_loads).where(
            training_context_loads.c.training_context_id == context_id
        )
    )


def insert_load(
    conn: sa.Connection, context_id: uuid.UUID, equipment_id: uuid.UUID,
    load_increments: list[Decimal] | None, bar_weight: Decimal | None,
) -> None:
    conn.execute(
        insert(training_context_loads).values(
            training_context_id=context_id, equipment_id=equipment_id,
            load_increments=load_increments, bar_weight=bar_weight,
        )
    )
