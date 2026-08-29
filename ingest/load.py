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
from schema import exercises

NAMESPACE = uuid.UUID("6f1a37e2-2c1e-5f8e-9d3b-000000000002")


def exercise_id(slug: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"loadout:exercise:{slug}")


def load(conn: sa.Connection, rows: list[Exercise]) -> None:
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


def main() -> None:
    rows = [Exercise(**d) for d in json.loads(NORMALIZED.read_text())]
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        load(conn, rows)
    print(f"loaded {len(rows)} exercises")


if __name__ == "__main__":
    main()
