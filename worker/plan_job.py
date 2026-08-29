"""The plan generation job.

This is where every piece composes: the context query resolves what the user has, the
catalog becomes candidates, the graph resolves substitutes, and the generator decides.
All the deciding is pure — this module is the I/O that feeds it and stores the answer.

Runs on RQ because plan generation is the one thing slow enough to be worth a queue
(PRD §6); everything else in the API is synchronous.
"""

import json
import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from db import DATABASE_URL
from engine import ENGINE_VERSION
from engine.generator import Candidate, Experience, Goal, Plan, Substitute, generate_plan
from engine.graph import Edge, Graph, Node, NoSubstituteFound, Reason, find_substitutes
from engine.progression.primitives import EquipmentLoads, expressible_loads
from engine.progression.volume import Landmark
from schema import exercise_state, exercises, muscle_groups, plans

ROOT = Path(__file__).resolve().parent.parent
CONTEXT_LOADS = (ROOT / "queries" / "context_loads.sql").read_text()
SUBSTITUTES = (ROOT / "queries" / "substitutes.sql").read_text()


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID | date | datetime):
        return str(value)
    if isinstance(value, Decimal):
        # str, not float: the whole point of Decimal here is that 2.5kg steps do not
        # survive binary floating point, and a round trip through JSON would undo it.
        return str(value)
    raise TypeError(f"cannot serialise {type(value).__name__}")


def plan_to_json(plan: Plan) -> dict[str, Any]:
    encoded: dict[str, Any] = json.loads(json.dumps(asdict(plan), default=_json_safe))
    return encoded


def _context_equipment(
    conn: sa.Connection, context_id: uuid.UUID
) -> dict[str, EquipmentLoads]:
    rows = conn.execute(sa.text(CONTEXT_LOADS), {"training_context_id": context_id}).all()
    return {
        r.slug: EquipmentLoads(
            slug=r.slug,
            increments=None if r.load_increments is None else tuple(r.load_increments),
            bar_weight=r.bar_weight,
        )
        for r in rows
    }


def _substitutes(
    conn: sa.Connection, exercise_id: uuid.UUID, available: frozenset[str]
) -> tuple[Substitute, ...]:
    got = conn.execute(
        sa.text(SUBSTITUTES), {"exercise_id": exercise_id, "max_depth": 3}
    ).all()
    nodes = [
        Node(r.id, r.slug, r.movement_pattern, frozenset(r.equipment), r.difficulty)
        for r in got
    ]
    edges = [
        Edge(r.id, uuid.UUID(e["to_id"]), e["edge_type"], e["delta"])
        for r in got
        for e in (r.out_edges if isinstance(r.out_edges, list) else json.loads(r.out_edges))
    ]
    try:
        # unavailable_now: the substitutes shipped with a plan are for the mid-session
        # case, where a lateral at the same difficulty keeps progression at parity (D15).
        found = find_substitutes(
            Graph.build(nodes, edges), exercise_id, available, Reason.UNAVAILABLE_NOW
        )
    except NoSubstituteFound:
        # A pattern with no reachable alternative is a catalog gap, not a failed plan.
        # The exercise is still prescribable; it just has nothing to fall back to.
        return ()
    return tuple(
        Substitute(
            exercise_id=c.node.id,
            slug=c.node.slug,
            equipment=tuple(sorted(c.node.equipment)),
        )
        for c in found
    )


def build_plan(
    conn: sa.Connection,
    user_id: uuid.UUID,
    context_id: uuid.UUID,
    days: list[date],
    time_budget_minutes: int,
    experience: Experience,
    goal: Goal,
) -> Plan:
    context = _context_equipment(conn, context_id)
    available = frozenset(context)

    catalog = [
        Candidate(
            exercise_id=r.id, slug=r.slug, movement_pattern=r.movement_pattern,
            primary_muscle=r.primary_muscles[0], equipment=frozenset(r.equipment),
            difficulty=r.difficulty, loadable=r.loadable,
        )
        for r in conn.execute(
            sa.select(
                exercises.c.id, exercises.c.slug, exercises.c.movement_pattern,
                exercises.c.primary_muscles, exercises.c.equipment,
                exercises.c.difficulty, exercises.c.loadable,
            )
        )
    ]
    landmarks = {
        r.slug: Landmark(r.mev, r.mav, r.mrv)
        for r in conn.execute(sa.select(muscle_groups))
    }
    previous_loads = {
        r.exercise_id: r.current_load
        for r in conn.execute(
            sa.select(exercise_state.c.exercise_id, exercise_state.c.current_load).where(
                exercise_state.c.user_id == user_id,
                exercise_state.c.current_load.is_not(None),
            )
        )
    }

    def can_express_load(c: Candidate) -> bool:
        try:
            return bool(expressible_loads(c.equipment, context))
        except (KeyError, ValueError):
            return False

    return generate_plan(
        days=days, catalog=catalog, available_equipment=available, landmarks=landmarks,
        time_budget_minutes=time_budget_minutes, experience=experience, goal=goal,
        substitutes_for=lambda eid: _substitutes(conn, eid, available),
        previous_loads=previous_loads,
        can_express_load=can_express_load,
    )


def generate(
    user_id: str,
    context_id: str,
    days: list[str],
    time_budget_minutes: int,
    experience: str,
    goal: str,
) -> str:
    """RQ entry point. Primitives only in the signature, since arguments are pickled.

    Returns the plan id, which is what `GET /jobs/{id}` hands back on success.
    """
    uid, cid = uuid.UUID(user_id), uuid.UUID(context_id)
    parsed = sorted(date.fromisoformat(d) for d in days)
    plan_id = uuid.uuid4()
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        plan = build_plan(
            conn, uid, cid, parsed, time_budget_minutes,
            Experience(experience), Goal(goal),
        )
        # Monday of the week the first session falls in.
        week_of = parsed[0] - timedelta(days=parsed[0].weekday())
        stmt = insert(plans).values(
            id=plan_id, user_id=uid, training_context_id=cid, week_of=week_of,
            generated_at=datetime.now(UTC), engine_version=ENGINE_VERSION,
            payload=plan_to_json(plan),
        )
        # Regenerating a week replaces it rather than accumulating; the engine is
        # deterministic, so the row is a cache and the newest one wins.
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["user_id", "week_of"],
                set_={
                    "id": stmt.excluded.id,
                    "training_context_id": stmt.excluded.training_context_id,
                    "generated_at": stmt.excluded.generated_at,
                    "engine_version": stmt.excluded.engine_version,
                    "payload": stmt.excluded.payload,
                },
            )
        )
    engine.dispose()
    return str(plan_id)
