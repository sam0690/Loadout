"""The recursive CTE in queries/substitutes.sql has to actually run.

Unexecuted SQL is untested code. This loads a small graph into the real database and
checks the query's shape and depth bound; the ranking logic itself lives in the engine
and is property-tested separately.
"""

import json
import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from db import DATABASE_URL
from engine.graph import Edge, Graph, Node, Reason, find_substitutes
from schema import exercise_edges, exercises

QUERY = (Path(__file__).resolve().parent.parent / "queries" / "substitutes.sql").read_text()

CHAIN = [
    ("q_bench", {"barbell", "plates", "flat_bench"}, 6),
    ("q_dbpress", {"dumbbells"}, 5),
    ("q_pushup", set(), 3),
    ("q_kneepushup", set(), 2),
    ("q_squat", set(), 4),  # a different pattern, must never be traversed into
]


@pytest.fixture(scope="module")
def seeded() -> Iterator[sa.Engine]:
    engine = sa.create_engine(DATABASE_URL)
    ids = {slug: uuid.uuid5(uuid.NAMESPACE_OID, slug) for slug, _, _ in CHAIN}
    with engine.begin() as c:
        c.execute(sa.delete(exercises).where(exercises.c.slug.in_(list(ids))))
        for slug, eq, diff in CHAIN:
            c.execute(
                sa.insert(exercises).values(
                    id=ids[slug], slug=slug, name=slug,
                    movement_pattern="squat" if slug == "q_squat" else "horizontal_press",
                    primary_muscles=["chest"] if slug != "q_squat" else ["quads"],
                    secondary_muscles=[], equipment=sorted(eq),
                    difficulty=diff, unilateral=False, loadable=bool(eq),
                )
            )
        for a, b, t, d in [
            ("q_bench", "q_dbpress", "equipment_downgrade", -1),
            ("q_dbpress", "q_pushup", "equipment_downgrade", -2),
            ("q_pushup", "q_kneepushup", "difficulty_step", -1),
            ("q_bench", "q_squat", "equipment_downgrade", -2),  # cross-pattern trap
        ]:
            c.execute(
                sa.insert(exercise_edges).values(
                    from_id=ids[a], to_id=ids[b], edge_type=t, delta=d
                )
            )
    yield engine
    with engine.begin() as c:
        c.execute(sa.delete(exercises).where(exercises.c.slug.in_(list(ids))))


def rows(engine: sa.Engine, slug: str, depth: int = 3) -> Sequence[sa.Row[Any]]:
    with engine.connect() as c:
        origin = c.execute(
            sa.select(exercises.c.id).where(exercises.c.slug == slug)
        ).scalar_one()
        return c.execute(
            sa.text(QUERY), {"exercise_id": origin, "max_depth": depth}
        ).all()


def test_query_runs_and_respects_the_depth_bound(seeded: sa.Engine) -> None:
    got = rows(seeded, "q_bench", depth=3)
    assert {r.slug for r in got} == {"q_bench", "q_dbpress", "q_pushup", "q_kneepushup"}
    assert max(r.depth for r in got) <= 3
    assert {r.slug: r.depth for r in got}["q_kneepushup"] == 3


def test_query_never_leaves_the_origins_movement_pattern(seeded: sa.Engine) -> None:
    """There is a cross-pattern edge from q_bench to q_squat; it must not be followed."""
    got = rows(seeded, "q_bench")
    assert "q_squat" not in {r.slug for r in got}
    assert {r.movement_pattern for r in got} == {"horizontal_press"}


def test_a_shallower_bound_returns_less(seeded: sa.Engine) -> None:
    assert {r.slug for r in rows(seeded, "q_bench", depth=1)} == {"q_bench", "q_dbpress"}


def test_query_output_feeds_the_engine_unchanged(seeded: sa.Engine) -> None:
    """The whole point of the split: the caller loads, the engine decides."""
    got = rows(seeded, "q_bench")
    nodes = [
        Node(r.id, r.slug, r.movement_pattern, frozenset(r.equipment), r.difficulty)
        for r in got
    ]
    edges = [
        Edge(r.id, uuid.UUID(e["to_id"]), e["edge_type"], e["delta"])
        for r in got
        for e in (r.out_edges if isinstance(r.out_edges, list) else json.loads(r.out_edges))
    ]
    graph = Graph.build(nodes, edges)
    origin = next(n for n in nodes if n.slug == "q_bench")

    got_subs = find_substitutes(
        graph, origin.id, frozenset(), Reason.UNAVAILABLE_OWNED
    )
    # Only the two bodyweight nodes fit an empty equipment set, nearest first.
    assert [c.node.slug for c in got_subs] == ["q_pushup", "q_kneepushup"]
    assert [c.hops for c in got_subs] == [2, 3]
