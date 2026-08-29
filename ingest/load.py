"""Stage 3: normalized exercises into the catalog.

    uv run python -m ingest.load

Idempotent on slug, same convergence rule as the equipment loader. Equipment slugs are
resolved through the alias table rather than trusted, so a normalize map that drifts out
of step with seeds/equipment.yaml fails loudly instead of writing a dangling reference.
"""

import json
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from db import DATABASE_URL
from ingest.equipment import resolve_slug
from ingest.normalize import NORMALIZED, Exercise
from ingest.terminals import read_terminals
from schema import exercises

NAMESPACE = uuid.UUID("6f1a37e2-2c1e-5f8e-9d3b-000000000002")


def exercise_id(slug: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"loadout:exercise:{slug}")


def load(conn: sa.Connection, rows: list[Exercise]) -> None:
    # Same convergence rule as the equipment loader: rows dropped from the normalized
    # set are dropped here. Without it a narrowed selection leaves the old catalog
    # behind and the table grows past what normalize actually chose. Edges cascade.
    conn.execute(
        sa.delete(exercises).where(exercises.c.slug.notin_([r.slug for r in rows]))
    )
    for r in rows:
        row: dict[str, Any] = {
            "id": exercise_id(r.slug),
            "slug": r.slug,
            "name": r.name,
            "movement_pattern": r.movement_pattern,
            "primary_muscles": r.primary_muscles,
            "secondary_muscles": r.secondary_muscles,
            # Through the alias table, not trusted: a normalize map that drifts out of
            # step with seeds/equipment.yaml must fail here, not write a dangling slug.
            "equipment": [resolve_slug(conn, s) for s in r.equipment],
            "difficulty": r.difficulty,
            "unilateral": r.unilateral,
            "loadable": r.loadable,
        }
        stmt = insert(exercises).values(row)
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["slug"],
                set_={k: stmt.excluded[k] for k in row if k != "id"},
            )
        )


def full_catalog() -> list[Exercise]:
    """Everything the catalog contains: ingested plus hand-authored.

    One definition, because the loader converges on exactly this set and anything left
    out of it gets deleted.
    """
    return [Exercise(**d) for d in json.loads(NORMALIZED.read_text())] + read_terminals()


def main() -> None:
    rows = full_catalog()
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        load(conn, rows)
    print(f"loaded {len(rows)} exercises ({len(read_terminals())} hand-authored)")


if __name__ == "__main__":
    main()
