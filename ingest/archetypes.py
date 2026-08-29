"""Load the gym archetype presets.

Same convergence rule as the equipment loader: the YAML is the source of truth, so a
preset dropped from the file is dropped from the database rather than left behind.

    uv run python -m ingest.archetypes
"""

import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa
import yaml
from sqlalchemy.dialects.postgresql import insert

from db import DATABASE_URL
from ingest.equipment import resolve_slug
from schema import equipment, gym_archetypes

SEED = Path(__file__).resolve().parent.parent / "seeds" / "gym_archetypes.yaml"
NAMESPACE = uuid.UUID("6f1a37e2-2c1e-5f8e-9d3b-000000000003")


def archetype_id(slug: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"loadout:archetype:{slug}")


def read_seed(path: Path = SEED) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = yaml.safe_load(path.read_text())
    for e in entries:
        if not e.get("equipment"):
            raise ValueError(f"{e['slug']}: an archetype with no equipment is not a gym")
    return entries


def load(conn: sa.Connection, entries: list[dict[str, Any]]) -> None:
    conn.execute(
        gym_archetypes.delete().where(
            gym_archetypes.c.slug.notin_([e["slug"] for e in entries])
        )
    )
    for e in entries:
        # Through the alias table, so a typo here fails the seed loudly rather than
        # quietly producing a thinner gym than the user actually has.
        ids = [
            conn.execute(
                sa.select(equipment.c.id).where(
                    equipment.c.slug == resolve_slug(conn, slug)
                )
            ).scalar_one()
            for slug in e["equipment"]
        ]
        row = {
            "id": archetype_id(e["slug"]),
            "slug": e["slug"],
            "name": e["name"],
            "equipment_ids": ids,
        }
        stmt = insert(gym_archetypes).values(row)
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["slug"],
                set_={k: stmt.excluded[k] for k in row if k != "id"},
            )
        )


def main() -> None:
    entries = read_seed()
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        load(conn, entries)
    print(f"loaded {len(entries)} gym archetypes")


if __name__ == "__main__":
    main()
