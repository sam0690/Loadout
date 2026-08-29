"""Substitution graph traversal. Pure functions (CLAUDE.md constraint 1).

No database, no clock, no randomness. The caller loads the graph — see
queries/substitutes.sql — and passes it in, so a user's whole history can be replayed
through a new engine version and diffed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

MAX_DEPTH = 3

EdgeType = Literal["equipment_downgrade", "difficulty_step", "lateral_equivalent"]


class Reason(StrEnum):
    """Why the prescribed exercise cannot be performed (PRD §2)."""

    UNAVAILABLE_OWNED = "unavailable_owned"  # user does not own it (home)
    UNAVAILABLE_HERE = "unavailable_here"  # this gym does not have it
    UNAVAILABLE_NOW = "unavailable_now"  # someone else is on it, mid-session


# Traversal order per reason (build prompt 0.4). unavailable_now wants an equivalent at
# the same difficulty so progression state carries at parity (D15); the other two mean
# the equipment is gone for the whole session, so downgrade first. difficulty_step is
# last everywhere: it never changes equipment, so it cannot solve an equipment problem
# on its own — it only refines what a downgrade already reached.
_ORDER: dict[Reason, tuple[EdgeType, ...]] = {
    Reason.UNAVAILABLE_NOW: ("lateral_equivalent", "equipment_downgrade", "difficulty_step"),
    Reason.UNAVAILABLE_OWNED: ("equipment_downgrade", "lateral_equivalent", "difficulty_step"),
    Reason.UNAVAILABLE_HERE: ("equipment_downgrade", "lateral_equivalent", "difficulty_step"),
}


class NoSubstituteFound(LookupError):
    """No reachable node satisfies the available equipment (D12).

    Raised rather than returning an empty list: an empty plan is a silent failure and
    CLAUDE.md requires the engine to fail loudly.
    """


@dataclass(frozen=True)
class Node:
    id: uuid.UUID
    slug: str
    movement_pattern: str
    equipment: frozenset[str]
    difficulty: int


@dataclass(frozen=True)
class Edge:
    from_id: uuid.UUID
    to_id: uuid.UUID
    edge_type: EdgeType
    delta: int


@dataclass(frozen=True)
class Candidate:
    node: Node
    hops: int
    delta: int  # cumulative difficulty change from the origin
    path: tuple[EdgeType, ...]


@dataclass(frozen=True)
class Graph:
    nodes: dict[uuid.UUID, Node]
    out_edges: dict[uuid.UUID, tuple[Edge, ...]] = field(default_factory=dict)

    @classmethod
    def build(cls, nodes: list[Node], edges: list[Edge]) -> Graph:
        by_id = {n.id: n for n in nodes}
        out: dict[uuid.UUID, list[Edge]] = {}
        for e in edges:
            # An edge to or from an exercise we do not have is a broken catalog, not
            # something to route around silently.
            if e.from_id not in by_id or e.to_id not in by_id:
                raise ValueError(f"edge references an unknown exercise: {e}")
            out.setdefault(e.from_id, []).append(e)
        return cls(nodes=by_id, out_edges={k: tuple(v) for k, v in out.items()})


def find_substitutes(
    graph: Graph,
    exercise_id: uuid.UUID,
    available_equipment: frozenset[str],
    reason: Reason,
    max_depth: int = MAX_DEPTH,
) -> list[Candidate]:
    """Ranked substitutes for `exercise_id`, reachable within `max_depth` hops.

    Ranked by fewest hops, then by the traversal order `reason` implies, then by the
    smallest absolute difficulty change, then by slug. The last key is not cosmetic:
    replay has to be deterministic, so ties may never order arbitrarily (D6).
    """
    origin = graph.nodes.get(exercise_id)
    if origin is None:
        raise NoSubstituteFound(f"{exercise_id} is not in the graph")

    priority = {t: i for i, t in enumerate(_ORDER[reason])}
    # Breadth-first, so the first time a node is reached is by a shortest path and the
    # visited set alone bounds the work. Termination is structural: every node is
    # expanded at most once and depth is capped.
    best: dict[uuid.UUID, Candidate] = {}
    frontier = [Candidate(origin, hops=0, delta=0, path=())]
    seen = {origin.id}

    for _ in range(max_depth):
        nxt: list[Candidate] = []
        for current in frontier:
            for edge in _sorted_edges(graph, current.node.id, priority):
                target = graph.nodes[edge.to_id]
                # Never cross movement patterns — a substitute that trains a different
                # movement is not a substitute (CLAUDE.md, PRD §7).
                if target.movement_pattern != origin.movement_pattern:
                    continue
                if edge.to_id in seen:
                    continue
                seen.add(edge.to_id)
                found = Candidate(
                    node=target,
                    hops=current.hops + 1,
                    delta=current.delta + edge.delta,
                    path=(*current.path, edge.edge_type),
                )
                nxt.append(found)
                if target.equipment <= available_equipment:
                    best[target.id] = found
        frontier = nxt
        if not frontier:
            break

    if not best:
        raise NoSubstituteFound(
            f"no substitute for {origin.slug!r} within {max_depth} hops that fits "
            f"{sorted(available_equipment)}"
        )
    return sorted(best.values(), key=lambda c: _rank(c, priority))


def _sorted_edges(
    graph: Graph, node_id: uuid.UUID, priority: dict[EdgeType, int]
) -> list[Edge]:
    return sorted(
        graph.out_edges.get(node_id, ()),
        key=lambda e: (priority[e.edge_type], graph.nodes[e.to_id].slug),
    )


def _rank(c: Candidate, priority: dict[EdgeType, int]) -> tuple[int, int, int, str]:
    # The worst edge type on the path decides, so for unavailable_now a pure-lateral
    # route beats a same-length route that had to downgrade.
    worst = max((priority[t] for t in c.path), default=0)
    return (c.hops, worst, abs(c.delta), c.node.slug)
