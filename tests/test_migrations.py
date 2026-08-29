"""Acceptance for 0.1: the migration round-trips, and it matches schema.py.

Needs the compose database up: `docker compose up -d`.
"""

import subprocess

import pytest
import sqlalchemy as sa

from db import DATABASE_URL

TABLES = {
    "equipment", "equipment_aliases", "exercises", "exercise_edges",
    "gym_archetypes", "muscle_groups", "training_contexts",
}


def alembic(*args: str) -> None:
    subprocess.run(["uv", "run", "alembic", *args], check=True, capture_output=True)


@pytest.fixture
def engine() -> sa.Engine:
    return sa.create_engine(DATABASE_URL)


def table_names(engine: sa.Engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


def test_upgrade_then_downgrade_leaves_nothing_behind(engine: sa.Engine) -> None:
    alembic("upgrade", "head")
    assert table_names(engine) >= TABLES

    alembic("downgrade", "base")
    # alembic_version survives by design; nothing of ours may.
    assert table_names(engine) - {"alembic_version"} == set()


def test_landmarks_are_seeded_and_ordered(engine: sa.Engine) -> None:
    alembic("upgrade", "head")
    with engine.connect() as c:
        rows = c.execute(
            sa.text("SELECT slug, mev, mav, mrv FROM muscle_groups ORDER BY slug")
        ).all()
    assert len(rows) == 16, "D4 defines 16 muscle groups"
    assert all(mev <= mav <= mrv for _, mev, mav, mrv in rows)


def test_schema_py_has_not_drifted_from_the_migration(engine: sa.Engine) -> None:
    """The migration is a frozen snapshot and schema.py is live, so they can diverge.

    Autogenerate against an upgraded database must find nothing to do.
    """
    alembic("upgrade", "head")
    out = subprocess.run(
        ["uv", "run", "alembic", "check"], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stdout + out.stderr


def test_lateral_edges_must_have_zero_delta(engine: sa.Engine) -> None:
    """D6 defines lateral_equivalent as zero-delta, so the database refuses otherwise."""
    alembic("upgrade", "head")
    ex = (
        "INSERT INTO exercises VALUES "
        "(:id, :slug, 'n', 'squat', '{quads}', '{}', '{}', 5, false, true)"
    )
    with engine.begin() as c:
        a = "11111111-1111-1111-1111-111111111111"
        b = "22222222-2222-2222-2222-222222222222"
        c.execute(sa.text(ex), {"id": a, "slug": "a"})
        c.execute(sa.text(ex), {"id": b, "slug": "b"})
    with engine.begin() as c, pytest.raises(sa.exc.IntegrityError):
        c.execute(
            sa.text(
                "INSERT INTO exercise_edges VALUES (:a, :b, 'lateral_equivalent', 1)"
            ),
            {"a": a, "b": b},
        )
    with engine.begin() as c:
        c.execute(sa.text("DELETE FROM exercises WHERE id IN (:a, :b)"), {"a": a, "b": b})
