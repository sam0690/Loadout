"""Load the canonical equipment taxonomy from seeds/equipment.yaml.

Idempotent: the YAML is the source of truth and a run converges the database onto it,
so running twice changes nothing. Ingest resolves brand names through the alias table
or raises — it never invents a canonical row (PRD §7).

    uv run python -m ingest.equipment
"""

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, TypedDict

import sqlalchemy as sa
import yaml
from sqlalchemy.dialects.postgresql import insert

from db import DATABASE_URL
from schema import equipment, equipment_aliases

SEED = Path(__file__).resolve().parent.parent / "seeds" / "equipment.yaml"

# Stable ids across runs and machines, so gym_archetypes.equipment_ids stays valid
# without a lookup pass and a re-seed doesn't orphan anything.
NAMESPACE = uuid.UUID("6f1a37e2-2c1e-5f8e-9d3b-000000000001")


class UnknownEquipment(KeyError):
    """A raw equipment string that resolves to no canonical row."""


class Alias(TypedDict):
    alias: str
    source: str


def equipment_id(slug: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"loadout:equipment:{slug}")


def read_seed(path: Path = SEED) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = yaml.safe_load(path.read_text())
    for e in entries:
        inc = e.get("load_increments")
        if inc is None:
            continue
        # Decimal, not float: the column is NUMERIC and 2.5kg steps accumulate badly in
        # binary floating point. Also keeps the array a single type for psycopg.
        inc = [Decimal(str(x)) for x in inc]
        # The DB checks class and movement_patterns. Sortedness it cannot, and 1.1's
        # "next available increment" is meaningless on an unsorted list.
        if inc != sorted(inc):
            raise ValueError(f"{e['slug']}: load_increments must be sorted ascending")
        if any(x <= 0 for x in inc):
            raise ValueError(f"{e['slug']}: load_increments must be positive")
        e["load_increments"] = inc
    return entries


def load(conn: sa.Connection, entries: list[dict[str, Any]]) -> None:
    # Rows dropped from the seed are dropped here, before the upserts. Convergence has
    # to include deletions or the seed is not the source of truth, and a canonical row
    # that gets renamed leaves its aliases behind to collide with the new row's on the
    # global unique(lower(alias)) index. Aliases cascade.
    conn.execute(
        sa.delete(equipment).where(equipment.c.slug.notin_([e["slug"] for e in entries]))
    )
    for e in entries:
        eid = equipment_id(e["slug"])
        row = {
            "id": eid,
            "slug": e["slug"],
            "class": e["class"],
            "movement_patterns": e["movement_patterns"],
            "is_fixed_path": e["is_fixed_path"],
            "load_increments": e["load_increments"],
        }
        stmt = insert(equipment).values(row)
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["slug"],
                set_={k: stmt.excluded[k] for k in row if k != "id"},
            )
        )

        aliases: list[Alias] = e.get("aliases", [])
        for a in aliases:
            astmt = insert(equipment_aliases).values(
                equipment_id=eid, alias=a["alias"], source=a["source"]
            )
            conn.execute(
                astmt.on_conflict_do_update(
                    index_elements=["equipment_id", "alias"],
                    set_={"source": astmt.excluded.source},
                )
            )
        # The seed is authoritative, so an alias dropped from YAML is dropped here.
        conn.execute(
            sa.delete(equipment_aliases).where(
                equipment_aliases.c.equipment_id == eid,
                equipment_aliases.c.alias.notin_([a["alias"] for a in aliases]),
            )
        )


def resolve_slug(conn: sa.Connection, raw: str) -> str:
    """Canonical slug for a raw equipment string, matched case-insensitively.

    Raises rather than returning None: an unrecognized machine name means the taxonomy
    is wrong, and silently skipping it fragments the catalog (PRD §7, CLAUDE.md errors).
    """
    hit: str | None = conn.execute(
        sa.select(equipment.c.slug)
        .select_from(equipment.outerjoin(equipment_aliases))
        .where(
            sa.or_(
                sa.func.lower(equipment.c.slug) == raw.strip().lower(),
                sa.func.lower(equipment_aliases.c.alias) == raw.strip().lower(),
            )
        )
        .limit(1)
    ).scalar_one_or_none()
    if hit is None:
        raise UnknownEquipment(
            f"{raw!r} matches no equipment slug or alias. Add it to seeds/equipment.yaml "
            f"as an alias of an existing row, or as a new canonical row if it truly is one."
        )
    return hit


def main() -> None:
    entries = read_seed()
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        load(conn, entries)
    print(f"loaded {len(entries)} equipment rows from {SEED.name}")


if __name__ == "__main__":
    main()
