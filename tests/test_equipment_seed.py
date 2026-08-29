"""Acceptance for 0.2: idempotent load, alias coverage, unknown aliases raise."""

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from db import DATABASE_URL
from ingest.equipment import UnknownEquipment, load, read_seed, resolve_slug
from schema import equipment, equipment_aliases


@pytest.fixture(scope="module")
def conn() -> Iterator[sa.Connection]:
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as c:
        load(c, read_seed())
        yield c


def snapshot(c: sa.Connection) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    eq = c.execute(sa.select(equipment).order_by(equipment.c.slug)).all()
    al = c.execute(
        sa.select(equipment_aliases).order_by(
            equipment_aliases.c.equipment_id, equipment_aliases.c.alias
        )
    ).all()
    return [tuple(r) for r in eq], [tuple(r) for r in al]


def test_loading_twice_changes_nothing(conn: sa.Connection) -> None:
    before = snapshot(conn)
    load(conn, read_seed())
    assert snapshot(conn) == before


def test_every_machine_has_at_least_two_aliases(conn: sa.Connection) -> None:
    counts = conn.execute(
        sa.select(equipment.c.slug, sa.func.count(equipment_aliases.c.alias))
        .select_from(equipment.outerjoin(equipment_aliases))
        .where(equipment.c["class"] == "machine")
        .group_by(equipment.c.slug)
    ).all()
    assert counts, "no machines loaded"
    thin = [slug for slug, n in counts if n < 2]
    assert not thin, f"machines with fewer than two aliases: {thin}"


def test_resolves_brand_names_case_insensitively(conn: sa.Connection) -> None:
    assert resolve_slug(conn, "Hammer Strength Iso-Lateral Row") == "seated_row_machine"
    assert resolve_slug(conn, "  life fitness pulldown  ") == "lat_pulldown"
    assert resolve_slug(conn, "TRX") == "suspension_trainer"
    assert resolve_slug(conn, "barbell") == "barbell"


def test_unknown_equipment_raises_rather_than_creating_a_row(conn: sa.Connection) -> None:
    before = conn.execute(sa.select(sa.func.count()).select_from(equipment)).scalar_one()
    with pytest.raises(UnknownEquipment):
        resolve_slug(conn, "Nautilus Nitro Plus Glute Drive")
    after = conn.execute(sa.select(sa.func.count()).select_from(equipment)).scalar_one()
    assert after == before


def test_load_increments_encode_the_d17_distinction(conn: sa.Connection) -> None:
    inc: dict[str, list[Decimal] | None] = {
        r.slug: r.load_increments
        for r in conn.execute(
            sa.select(equipment.c.slug, equipment.c.load_increments)
        ).all()
    }
    assert inc["barbell"] is None, "derived from bar weight plus plates"
    assert inc["dumbbells"], "a typical rack the context may override (D21)"
    assert inc["pull_up_bar"] == [], "nothing to load"
    assert inc["kettlebell"], "an enumerated set"
    assert inc["cable_stack"], "an enumerated stack"


def test_seed_rejects_unsorted_increments(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "- slug: x\n  class: bar\n  is_fixed_path: false\n"
        "  load_increments: [10, 5]\n  movement_patterns: []\n"
    )
    with pytest.raises(ValueError, match="sorted ascending"):
        read_seed(bad)


def test_a_row_dropped_from_the_seed_is_dropped_from_the_database(
    conn: sa.Connection,
) -> None:
    """Convergence includes deletion, or a renamed row leaves its aliases behind."""
    seed = read_seed()
    load(conn, [e for e in seed if e["slug"] != "pec_deck"])
    assert resolve_slug_or_none(conn, "pec_deck") is None
    assert conn.execute(
        sa.select(sa.func.count())
        .select_from(equipment_aliases)
        .where(equipment_aliases.c.alias == "butterfly machine")
    ).scalar_one() == 0

    load(conn, seed)
    assert resolve_slug(conn, "butterfly machine") == "pec_deck"


def resolve_slug_or_none(c: sa.Connection, slug: str) -> str | None:
    try:
        return resolve_slug(c, slug)
    except UnknownEquipment:
        return None
