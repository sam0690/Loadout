"""Property tests for engine/graph. The invariants in CLAUDE.md, over random graphs.

These matter more than the examples: the traversal is only worth having if it cannot
return an exercise the user is unable to perform, whatever the catalog looks like.
"""

import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from engine.graph import (
    Candidate,
    Edge,
    Graph,
    Node,
    NoSubstituteFound,
    Reason,
    find_substitutes,
)

PATTERNS = ["squat", "hinge", "horizontal_press", "vertical_pull"]
EQUIPMENT = ["barbell", "plates", "dumbbells", "kettlebell", "flat_bench", "pull_up_bar"]
EDGE_TYPES = ["equipment_downgrade", "difficulty_step", "lateral_equivalent"]


@st.composite
def graphs(draw: st.DrawFn) -> tuple[Graph, list[Node]]:
    n = draw(st.integers(min_value=2, max_value=9))
    nodes = [
        Node(
            id=uuid.UUID(int=i + 1),
            slug=f"ex_{i:02d}",
            movement_pattern=draw(st.sampled_from(PATTERNS)),
            equipment=frozenset(
                draw(st.lists(st.sampled_from(EQUIPMENT), max_size=3, unique=True))
            ),
            difficulty=draw(st.integers(min_value=1, max_value=10)),
        )
        for i in range(n)
    ]
    edges = []
    for a in nodes:
        for b in nodes:
            if a.id == b.id or not draw(st.booleans()):
                continue
            etype = draw(st.sampled_from(EDGE_TYPES))
            # D6: lateral edges are zero-delta by definition, as the DB enforces.
            delta = 0 if etype == "lateral_equivalent" else b.difficulty - a.difficulty
            edges.append(Edge(a.id, b.id, etype, delta))  # type: ignore[arg-type]
    return Graph.build(nodes, edges), nodes


def substitutes(
    graph: Graph, origin: Node, available: frozenset[str], reason: Reason, depth: int = 3
) -> list[Candidate]:
    try:
        return find_substitutes(graph, origin.id, available, reason, depth)
    except NoSubstituteFound:
        return []


SETTINGS = settings(
    max_examples=120, suppress_health_check=[HealthCheck.too_slow], deadline=None
)


@SETTINGS
@given(
    data=graphs(),
    available=st.frozensets(st.sampled_from(EQUIPMENT), max_size=6),
    reason=st.sampled_from(list(Reason)),
    depth=st.integers(min_value=1, max_value=3),
)
def test_never_returns_a_different_movement_pattern(
    data: tuple[Graph, list[Node]], available: frozenset[str], reason: Reason, depth: int
) -> None:
    graph, nodes = data
    for origin in nodes:
        for c in substitutes(graph, origin, available, reason, depth):
            assert c.node.movement_pattern == origin.movement_pattern


@SETTINGS
@given(
    data=graphs(),
    available=st.frozensets(st.sampled_from(EQUIPMENT), max_size=6),
    reason=st.sampled_from(list(Reason)),
    depth=st.integers(min_value=1, max_value=3),
)
def test_never_returns_equipment_the_user_does_not_have(
    data: tuple[Graph, list[Node]], available: frozenset[str], reason: Reason, depth: int
) -> None:
    graph, nodes = data
    for origin in nodes:
        for c in substitutes(graph, origin, available, reason, depth):
            assert c.node.equipment <= available


@SETTINGS
@given(
    data=graphs(),
    available=st.frozensets(st.sampled_from(EQUIPMENT), max_size=6),
    reason=st.sampled_from(list(Reason)),
    depth=st.integers(min_value=1, max_value=3),
)
def test_terminates_within_max_depth(
    data: tuple[Graph, list[Node]], available: frozenset[str], reason: Reason, depth: int
) -> None:
    graph, nodes = data
    for origin in nodes:
        for c in substitutes(graph, origin, available, reason, depth):
            assert 1 <= c.hops <= depth
            assert len(c.path) == c.hops


@SETTINGS
@given(
    data=graphs(),
    available=st.frozensets(st.sampled_from(EQUIPMENT), max_size=6),
    reason=st.sampled_from(list(Reason)),
)
def test_never_returns_the_origin_and_never_repeats(
    data: tuple[Graph, list[Node]], available: frozenset[str], reason: Reason
) -> None:
    graph, nodes = data
    for origin in nodes:
        got = substitutes(graph, origin, available, reason)
        ids = [c.node.id for c in got]
        assert origin.id not in ids
        assert len(ids) == len(set(ids))


@SETTINGS
@given(
    data=graphs(),
    available=st.frozensets(st.sampled_from(EQUIPMENT), max_size=6),
    reason=st.sampled_from(list(Reason)),
)
def test_ranking_is_total_and_deterministic(
    data: tuple[Graph, list[Node]], available: frozenset[str], reason: Reason
) -> None:
    """Replay diffs engine versions, so ties may never order arbitrarily (D6)."""
    graph, nodes = data
    for origin in nodes:
        once = substitutes(graph, origin, available, reason)
        twice = substitutes(graph, origin, available, reason)
        assert [c.node.id for c in once] == [c.node.id for c in twice]
        keys = [(c.hops, abs(c.delta), c.node.slug) for c in once]
        assert keys == sorted(keys) or all(
            a[0] <= b[0] for a, b in zip(keys, keys[1:], strict=False)
        )


@SETTINGS
@given(
    data=graphs(),
    available=st.frozensets(st.sampled_from(EQUIPMENT), max_size=6),
    reason=st.sampled_from(list(Reason)),
)
def test_fewer_hops_always_ranks_first(
    data: tuple[Graph, list[Node]], available: frozenset[str], reason: Reason
) -> None:
    graph, nodes = data
    for origin in nodes:
        hops = [c.hops for c in substitutes(graph, origin, available, reason)]
        assert hops == sorted(hops)


@SETTINGS
@given(data=graphs(), reason=st.sampled_from(list(Reason)))
def test_a_deeper_search_never_loses_a_shallower_result(
    data: tuple[Graph, list[Node]], reason: Reason
) -> None:
    graph, nodes = data
    everything = frozenset(EQUIPMENT)
    for origin in nodes:
        shallow = {c.node.id for c in substitutes(graph, origin, everything, reason, 1)}
        deep = {c.node.id for c in substitutes(graph, origin, everything, reason, 3)}
        assert shallow <= deep


# --- worked examples ---------------------------------------------------------


def line(*specs: tuple[str, set[str], int]) -> tuple[Graph, list[Node]]:
    nodes = [
        Node(uuid.UUID(int=i + 1), slug, "horizontal_press", frozenset(eq), diff)
        for i, (slug, eq, diff) in enumerate(specs)
    ]
    return Graph.build(nodes, []), nodes


def test_unavailable_now_prefers_a_lateral_over_a_downgrade() -> None:
    (_, nodes) = line(
        ("bench_press", {"barbell", "plates", "flat_bench"}, 6),
        ("chest_press_machine", {"dumbbells"}, 6),
        ("push_up", set(), 3),
    )
    bench, lateral, downgrade = nodes
    graph = Graph.build(
        nodes,
        [
            Edge(bench.id, lateral.id, "lateral_equivalent", 0),
            Edge(bench.id, downgrade.id, "equipment_downgrade", -3),
        ],
    )
    got = find_substitutes(
        graph, bench.id, frozenset({"dumbbells"}), Reason.UNAVAILABLE_NOW
    )
    assert [c.node.slug for c in got] == ["chest_press_machine", "push_up"]


def test_unavailable_owned_prefers_the_downgrade() -> None:
    (_, nodes) = line(
        ("bench_press", {"barbell", "plates", "flat_bench"}, 6),
        ("db_press", {"dumbbells"}, 5),
        ("push_up", set(), 3),
    )
    bench, lateral, downgrade = nodes
    graph = Graph.build(
        nodes,
        [
            Edge(bench.id, lateral.id, "lateral_equivalent", 0),
            Edge(bench.id, downgrade.id, "equipment_downgrade", -3),
        ],
    )
    got = find_substitutes(
        graph, bench.id, frozenset({"dumbbells"}), Reason.UNAVAILABLE_OWNED
    )
    assert [c.node.slug for c in got] == ["push_up", "db_press"]


def test_raises_rather_than_returning_an_empty_plan() -> None:
    """D12 and CLAUDE.md: a missing exercise raises, it does not return nothing."""
    graph, nodes = line(("bench_press", {"barbell", "plates"}, 6))
    with pytest.raises(NoSubstituteFound):
        find_substitutes(graph, nodes[0].id, frozenset(), Reason.UNAVAILABLE_OWNED)


def test_an_edge_to_an_unknown_exercise_is_a_broken_catalog() -> None:
    graph, nodes = line(("a", set(), 1), ("b", set(), 2))
    with pytest.raises(ValueError, match="unknown exercise"):
        Graph.build(
            list(graph.nodes.values()),
            [Edge(nodes[0].id, uuid.UUID(int=99), "difficulty_step", 1)],
        )
