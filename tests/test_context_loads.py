"""Task A: a training context resolves to loads, and the query composes with the engine."""

import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa

from db import DATABASE_URL
from engine.progression import (
    AmbiguousLoads,
    EquipmentLoads,
    barbell_loads,
    expressible_loads,
)
from schema import equipment, gym_archetypes, training_context_loads, training_contexts

D = Decimal
QUERY = (Path(__file__).resolve().parent.parent / "queries" / "context_loads.sql").read_text()
USER = uuid.UUID(int=7)


def loads(slug: str, inc: list[str] | None, bar: str | None = None) -> EquipmentLoads:
    return EquipmentLoads(
        slug,
        None if inc is None else tuple(D(x) for x in inc),
        None if bar is None else D(bar),
    )


# --- the pure composition ----------------------------------------------------


def test_a_bodyweight_exercise_has_nothing_to_load() -> None:
    assert expressible_loads([], {}) == []


def test_a_bench_alone_is_not_loadable() -> None:
    ctx = {"flat_bench": loads("flat_bench", [])}
    assert expressible_loads(["flat_bench"], ctx) == []


def test_a_bench_does_not_confuse_a_dumbbell_press() -> None:
    ctx = {
        "dumbbells": loads("dumbbells", ["5", "10", "15"]),
        "flat_bench": loads("flat_bench", []),
    }
    assert expressible_loads(["dumbbells", "flat_bench"], ctx) == [D(5), D(10), D(15)]


def test_a_barbell_is_derived_from_bar_weight_and_plates() -> None:
    ctx = {
        "barbell": loads("barbell", None, bar="20"),
        "plates": loads("plates", ["1.25", "2.5", "5"]),
    }
    got = expressible_loads(["barbell", "plates"], ctx, ceiling=D("60"))
    assert got == barbell_loads(D("20"), [D("1.25"), D("2.5"), D("5")], D("60"))
    assert got[0] == D("20") and D("22.5") in got


def test_a_bar_with_no_plates_still_expresses_one_load() -> None:
    ctx = {"barbell": loads("barbell", None, bar="20"), "plates": loads("plates", [])}
    assert expressible_loads(["barbell", "plates"], ctx) == [D("20")]


def test_a_barbell_without_a_declared_bar_weight_raises() -> None:
    ctx = {"barbell": loads("barbell", None), "plates": loads("plates", ["5"])}
    with pytest.raises(ValueError, match="bar_weight"):
        expressible_loads(["barbell", "plates"], ctx)


def test_two_loadable_items_is_a_catalog_error_not_a_guess() -> None:
    ctx = {
        "dumbbells": loads("dumbbells", ["5", "10"]),
        "kettlebell": loads("kettlebell", ["8", "12"]),
    }
    with pytest.raises(AmbiguousLoads):
        expressible_loads(["dumbbells", "kettlebell"], ctx)


def test_equipment_the_context_lacks_raises() -> None:
    with pytest.raises(KeyError, match="cable_stack"):
        expressible_loads(["cable_stack"], {})


# --- the query, executed ------------------------------------------------------


@pytest.fixture
def context(request: pytest.FixtureRequest) -> sa.Engine:
    """A context: archetype gives dumbbells + barbell + plates, minus the barbell."""
    engine = sa.create_engine(DATABASE_URL)
    ctx_id, arch_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as c:
        ids: dict[str, uuid.UUID] = {
            r.slug: r.id
            for r in c.execute(
                sa.select(equipment.c.slug, equipment.c.id).where(
                    equipment.c.slug.in_(["dumbbells", "barbell", "plates", "kettlebell"])
                )
            )
        }
        c.execute(
            sa.insert(gym_archetypes).values(
                id=arch_id, slug=f"t_{arch_id.hex[:8]}", name="test",
                equipment_ids=[ids["dumbbells"], ids["barbell"], ids["plates"]],
            )
        )
        c.execute(
            sa.insert(training_contexts).values(
                id=ctx_id, user_id=USER, label="home", archetype_id=arch_id,
                equipment_added=[ids["kettlebell"]], equipment_removed=[ids["barbell"]],
                is_default=True,
            )
        )
        # D21: this context's rack is smaller than the catalog default.
        c.execute(
            sa.insert(training_context_loads).values(
                training_context_id=ctx_id, equipment_id=ids["dumbbells"],
                load_increments=[D(5), D(10), D(15), D(20)],
            )
        )
    request.addfinalizer(
        lambda: _cleanup(engine, ctx_id, arch_id)
    )
    engine.ctx_id = ctx_id  # type: ignore[attr-defined]
    return engine


def _cleanup(engine: sa.Engine, ctx_id: uuid.UUID, arch_id: uuid.UUID) -> None:
    with engine.begin() as c:
        c.execute(sa.delete(training_contexts).where(training_contexts.c.id == ctx_id))
        c.execute(sa.delete(gym_archetypes).where(gym_archetypes.c.id == arch_id))


def resolve(engine: sa.Engine) -> dict[str, EquipmentLoads]:
    with engine.connect() as c:
        rows = c.execute(
            sa.text(QUERY), {"training_context_id": engine.ctx_id}  # type: ignore[attr-defined]
        ).all()
    return {
        r.slug: EquipmentLoads(
            r.slug,
            None if r.load_increments is None else tuple(r.load_increments),
            r.bar_weight,
        )
        for r in rows
    }


def test_the_query_applies_d10s_merge(context: sa.Engine) -> None:
    got = resolve(context)
    assert "kettlebell" in got, "equipment_added"
    assert "barbell" not in got, "equipment_removed wins over the archetype preset"
    assert {"dumbbells", "plates", "kettlebell"} == set(got)


def test_an_override_wins_over_the_catalog_default(context: sa.Engine) -> None:
    got = resolve(context)
    assert got["dumbbells"].increments == (D(5), D(10), D(15), D(20))


def test_equipment_without_an_override_inherits_the_catalog(context: sa.Engine) -> None:
    got = resolve(context)
    assert got["kettlebell"].increments == (D(8), D(12), D(16), D(20), D(24), D(28), D(32), D(40))


def test_the_query_feeds_the_engine_unchanged(context: sa.Engine) -> None:
    """The whole point of the split: the caller resolves, the engine composes."""
    got = resolve(context)
    assert expressible_loads(["dumbbells"], got) == [D(5), D(10), D(15), D(20)]


def test_a_row_asserting_nothing_is_rejected(context: sa.Engine) -> None:
    with context.begin() as c:
        ids = c.execute(
            sa.select(equipment.c.id).where(equipment.c.slug == "plates")
        ).scalar_one()
        with pytest.raises(sa.exc.IntegrityError):
            c.execute(
                sa.insert(training_context_loads).values(
                    training_context_id=context.ctx_id,  # type: ignore[attr-defined]
                    equipment_id=ids, load_increments=None, bar_weight=None,
                )
            )
