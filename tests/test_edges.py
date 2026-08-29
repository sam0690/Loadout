"""Acceptance for 0.5: no isolated nodes, every pattern with a terminal reaches it."""

import json
import uuid
from collections import defaultdict
from pathlib import Path

import pytest
import sqlalchemy as sa

from db import DATABASE_URL
from engine.graph import Edge, Graph, Node, NoSubstituteFound, Reason, find_substitutes
from ingest.edges import (
    SEED,
    GeneratedEdge,
    Row,
    find_gaps,
    find_orphans,
    generate,
    load_edges,
    read_catalog,
)
from ingest.load import full_catalog
from ingest.load import load as load_exercises
from schema import exercise_edges, exercises

QUERY = (Path(__file__).resolve().parent.parent / "queries" / "substitutes.sql").read_text()


@pytest.fixture(scope="module")
def seeded() -> sa.Engine:
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as c:
        load_exercises(c, full_catalog())
        load_edges(c, SEED)
    return engine


@pytest.fixture(scope="module")
def generated(seeded: sa.Engine) -> tuple[list[Row], list[GeneratedEdge]]:
    with seeded.connect() as c:
        rows, fixed = read_catalog(c)
    return rows, generate(rows, fixed)


def test_no_exercise_is_isolated(generated: tuple[list[Row], list[GeneratedEdge]]) -> None:
    rows, edges = generated
    isolated, _ = find_orphans(rows, edges)
    assert not isolated


def test_only_top_of_chain_nodes_lack_an_incoming_edge(
    generated: tuple[list[Row], list[GeneratedEdge]],
) -> None:
    """There is no equipment_upgrade edge type, so the most-equipped node is a source."""
    rows, edges = generated
    _, source_only = find_orphans(rows, edges)
    by_slug = {r.slug: r for r in rows}
    tiers_by_pattern: dict[str, set[int]] = defaultdict(set)
    from ingest.taxonomy import tier

    for r in rows:
        tiers_by_pattern[r.pattern].add(tier(r.equipment))
    for slug in source_only:
        r = by_slug[slug]
        assert tier(r.equipment) == max(tiers_by_pattern[r.pattern]), slug


def test_lateral_edges_are_always_zero_delta(
    generated: tuple[list[Row], list[GeneratedEdge]],
) -> None:
    """D6, also enforced by a CHECK constraint."""
    _, edges = generated
    assert all(e.delta == 0 for e in edges if e.edge_type == "lateral_equivalent")


def test_delta_is_always_the_difficulty_difference(
    generated: tuple[list[Row], list[GeneratedEdge]],
) -> None:
    rows, edges = generated
    d = {r.slug: r.difficulty for r in rows}
    for e in edges:
        if e.edge_type != "lateral_equivalent":
            assert e.delta == d[e.to_slug] - d[e.from_slug], e


def test_risky_edges_carry_a_doubt(
    generated: tuple[list[Row], list[GeneratedEdge]],
) -> None:
    """Flagged, not dropped and not silently trusted."""
    _, edges = generated
    laterals = [e for e in edges if e.edge_type == "lateral_equivalent"]
    assert laterals and all(e.doubts for e in laterals)


def test_every_pattern_with_a_terminal_reaches_it(seeded: sa.Engine) -> None:
    """The invariant that matters: no equipment, still a prescription."""
    with seeded.connect() as c:
        catalog = c.execute(
            sa.select(
                exercises.c.id, exercises.c.slug, exercises.c.movement_pattern,
                exercises.c.equipment,
            )
        ).all()
        has_terminal = {r.movement_pattern for r in catalog if not r.equipment}
        for row in catalog:
            if row.movement_pattern not in has_terminal or not row.equipment:
                continue
            got = c.execute(
                sa.text(QUERY), {"exercise_id": row.id, "max_depth": 3}
            ).all()
            nodes = [
                Node(r.id, r.slug, r.movement_pattern, frozenset(r.equipment), r.difficulty)
                for r in got
            ]
            edges = [
                Edge(r.id, uuid.UUID(x["to_id"]), x["edge_type"], x["delta"])
                for r in got
                for x in (
                    r.out_edges if isinstance(r.out_edges, list) else json.loads(r.out_edges)
                )
            ]
            subs = find_substitutes(
                Graph.build(nodes, edges), row.id, frozenset(), Reason.UNAVAILABLE_OWNED
            )
            assert subs, row.slug
            assert all(not s.node.equipment for s in subs), row.slug


def test_no_pattern_lacks_a_zero_equipment_terminal(seeded: sa.Engine) -> None:
    """D22 closed the seven gaps D12 recorded. This is what stops them reopening."""
    with seeded.connect() as c:
        rows, _ = read_catalog(c)
    assert find_gaps(rows) == []


def test_an_unreachable_target_still_raises_rather_than_returning_nothing() -> None:
    """D12's behaviour survives even though the catalog no longer triggers it."""
    lonely = Node(uuid.uuid4(), "lonely", "squat", frozenset({"barbell"}), 5)
    with pytest.raises(NoSubstituteFound):
        find_substitutes(
            Graph.build([lonely], []), lonely.id, frozenset(), Reason.UNAVAILABLE_OWNED
        )


def test_load_is_idempotent(seeded: sa.Engine) -> None:
    with seeded.begin() as c:
        n = load_edges(c, SEED)
        first = c.execute(sa.select(exercise_edges).order_by(*exercise_edges.c)).all()
        assert load_edges(c, SEED) == n
        assert c.execute(sa.select(exercise_edges).order_by(*exercise_edges.c)).all() == first


def test_load_rejects_an_edge_to_an_exercise_not_in_the_catalog(
    seeded: sa.Engine, tmp_path: Path
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- from: bodyweight_squat\n  to: nonexistent_exercise\n"
                   "  type: difficulty_step\n  delta: 1\n")
    with seeded.begin() as c, pytest.raises(KeyError, match="not in the catalog"):
        load_edges(c, bad)


def test_generation_refuses_to_clobber_a_reviewed_file() -> None:
    """The file exists to be hand-corrected; regenerating over it must be deliberate."""
    import subprocess

    out = subprocess.run(
        ["uv", "run", "python", "-m", "ingest.edges"], capture_output=True, text=True
    )
    assert out.returncode != 0
    assert "--force" in out.stderr
