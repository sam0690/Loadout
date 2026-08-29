"""1.4 against the real catalog and the real graph, not synthetic fixtures.

The property tests prove the invariants hold over random inputs. This proves the pieces
actually compose: query -> graph -> substitutes -> plan.
"""

import json
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa

from db import DATABASE_URL
from engine.generator import Candidate, Experience, Goal, generate_plan
from engine.graph import Edge, Graph, Node, NoSubstituteFound, Reason, find_substitutes
from engine.progression.volume import Landmark
from ingest.edges import SEED as EDGE_SEED
from ingest.edges import load_edges
from ingest.load import load as load_exercises
from ingest.normalize import run as normalize_run
from schema import exercises, muscle_groups

QUERY = (Path(__file__).resolve().parent.parent / "queries" / "substitutes.sql").read_text()
MONDAY = date(2026, 8, 31)
HOME = frozenset({"dumbbells", "flat_bench", "pull_up_bar", "resistance_bands"})


@pytest.fixture(scope="module")
def live() -> tuple[list[Candidate], dict[str, Landmark], sa.Engine]:
    """Loads its own catalog and edges rather than trusting the session seed.

    Deleting an exercise cascades to its edges, so any test that narrows the catalog
    silently empties the graph for whatever runs next. A fixture that reads the graph has
    to establish it, not assume it.
    """
    engine = sa.create_engine(DATABASE_URL)
    chosen, _ = normalize_run()
    with engine.begin() as c:
        load_exercises(c, chosen)
        load_edges(c, EDGE_SEED)
    with engine.connect() as c:
        rows = c.execute(
            sa.select(
                exercises.c.id, exercises.c.slug, exercises.c.movement_pattern,
                exercises.c.primary_muscles, exercises.c.equipment,
                exercises.c.difficulty, exercises.c.loadable,
            )
        ).all()
        landmarks = {
            r.slug: Landmark(r.mev, r.mav, r.mrv)
            for r in c.execute(sa.select(muscle_groups)).all()
        }
    catalog = [
        Candidate(
            exercise_id=r.id, slug=r.slug, movement_pattern=r.movement_pattern,
            primary_muscle=r.primary_muscles[0], equipment=frozenset(r.equipment),
            difficulty=r.difficulty, loadable=r.loadable,
        )
        for r in rows
    ]
    return catalog, landmarks, engine


def substitutes_via_graph(engine: sa.Engine) -> object:
    def resolve(exercise_id: uuid.UUID) -> tuple[uuid.UUID, ...]:
        with engine.connect() as c:
            got = c.execute(sa.text(QUERY), {"exercise_id": exercise_id, "max_depth": 3}).all()
        nodes = [
            Node(r.id, r.slug, r.movement_pattern, frozenset(r.equipment), r.difficulty)
            for r in got
        ]
        edges = [
            Edge(r.id, uuid.UUID(x["to_id"]), x["edge_type"], x["delta"])
            for r in got
            for x in (r.out_edges if isinstance(r.out_edges, list) else json.loads(r.out_edges))
        ]
        try:
            found = find_substitutes(
                Graph.build(nodes, edges), exercise_id, HOME, Reason.UNAVAILABLE_NOW
            )
        except NoSubstituteFound:
            return ()
        return tuple(c.node.id for c in found)

    return resolve


def test_a_real_home_plan_is_generated(
    live: tuple[list[Candidate], dict[str, Landmark], sa.Engine],
) -> None:
    catalog, landmarks, engine = live
    plan = generate_plan(
        days=[MONDAY, MONDAY + timedelta(days=2), MONDAY + timedelta(days=4)],
        catalog=catalog, available_equipment=HOME, landmarks=landmarks,
        time_budget_minutes=60, experience=Experience.INTERMEDIATE, goal=Goal.HYPERTROPHY,
        substitutes_for=substitutes_via_graph(engine),  # type: ignore[arg-type]
    )
    assert plan.sessions, "the real catalog should produce a real plan"
    for session in plan.sessions:
        for item in session.items:
            assert item.sets >= 1


def test_every_shipped_substitute_is_valid_for_the_same_pattern(
    live: tuple[list[Candidate], dict[str, Landmark], sa.Engine],
) -> None:
    """CLAUDE.md invariant 5, at the point the client actually consumes it.

    A substitute shipped with the plan is used offline with no chance to re-check it, so
    it must already be same-pattern and within the context's equipment.
    """
    catalog, landmarks, engine = live
    by_id = {c.exercise_id: c for c in catalog}
    plan = generate_plan(
        days=[MONDAY, MONDAY + timedelta(days=2)], catalog=catalog,
        available_equipment=HOME, landmarks=landmarks, time_budget_minutes=60,
        substitutes_for=substitutes_via_graph(engine),  # type: ignore[arg-type]
    )
    shipped = 0
    for session in plan.sessions:
        for item in session.items:
            for sub_id in item.substitutes:
                sub = by_id[sub_id]
                assert sub.movement_pattern == item.movement_pattern
                assert sub.equipment <= HOME
                shipped += 1
    assert shipped, "the seeded edges should yield at least some substitutes"


def test_the_plan_respects_the_real_landmarks(
    live: tuple[list[Candidate], dict[str, Landmark], sa.Engine],
) -> None:
    catalog, landmarks, engine = live
    plan = generate_plan(
        days=[MONDAY + timedelta(days=i * 2) for i in range(3)], catalog=catalog,
        available_equipment=HOME, landmarks=landmarks, time_budget_minutes=90,
        experience=Experience.ADVANCED,
    )
    for muscle, count in plan.weekly_hard_sets().items():
        assert count <= landmarks[muscle].mrv
