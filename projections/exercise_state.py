"""Fold the event log into exercise_state.

A projection is derived and rebuildable (CLAUDE.md constraint 2). If one is ever wrong we
replay; we do not patch. That property is only worth something if the rebuild is exact,
which is what `rebuild()` and its test exist to prove.

This module does I/O and is deliberately outside `engine/`: it calls the pure functions
there, it does not reimplement them.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from engine.progression.primitives import MAX_REPS_TO_FAILURE, best_e1rm_estimate
from schema import events, exercise_state


@dataclass(frozen=True)
class State:
    current_load: Decimal | None = None
    current_reps: int | None = None
    e1rm: Decimal | None = None
    consecutive_successes: int = 0
    consecutive_failures: int = 0
    is_estimated: bool = False
    last_performed_at: datetime | None = None


@dataclass(frozen=True)
class _Set:
    reps: int
    rir: int
    load: Decimal | None
    target_top: int | None
    target_bottom: int | None
    at: datetime


def local_day(at: datetime, tz: str) -> date:
    """The calendar day in the user's own zone (constraint 6, D14)."""
    return at.astimezone(ZoneInfo(tz)).date()


def _fold_session(state: State, sets: Sequence[_Set]) -> State:
    """One exercise, one local day. The limiting set decides, as in 1.2."""
    limiting = min(sets, key=lambda s: (s.reps, s.rir))
    last = max(sets, key=lambda s: s.at)

    e1rm = state.e1rm
    if last.load is not None and limiting.reps + limiting.rir <= MAX_REPS_TO_FAILURE:
        e1rm = best_e1rm_estimate(last.load, limiting.reps, limiting.rir)

    successes, failures = state.consecutive_successes, state.consecutive_failures
    if limiting.target_bottom is not None and limiting.target_top is not None:
        if limiting.reps < limiting.target_bottom:
            failures, successes = failures + 1, 0
        elif limiting.reps >= limiting.target_top and limiting.rir >= 1:
            successes, failures = successes + 1, 0
        else:
            failures = 0

    return State(
        current_load=last.load,
        current_reps=last.reps,
        e1rm=e1rm,
        consecutive_successes=successes,
        consecutive_failures=failures,
        # D15: the first logged session against a seeded node clears the flag.
        is_estimated=False,
        last_performed_at=last.at,
    )


def fold(rows: Iterable[sa.Row[Any]]) -> dict[tuple[uuid.UUID, uuid.UUID], State]:
    """Replay events in order into per-(user, exercise) state. Pure over its input.

    Sets are grouped into sessions by local calendar day, which is the same unit D14 uses
    for the fatigue gate and the only session boundary available before plans exist in
    2.2. A workout spanning local midnight counts as two, which is rare and harmless.
    """
    out: dict[tuple[uuid.UUID, uuid.UUID], State] = {}
    pending: dict[tuple[uuid.UUID, uuid.UUID, date], list[_Set]] = {}
    order: list[tuple[uuid.UUID, uuid.UUID, date]] = []

    def flush() -> None:
        """Fold every buffered session. Called before anything that reads `out`."""
        for bucket in order:
            user_id, exercise_id, _ = bucket
            key = (user_id, exercise_id)
            out[key] = _fold_session(out.get(key, State()), pending[bucket])
        pending.clear()
        order.clear()

    for row in rows:
        if row.type == "exercise_swapped":
            # Sessions are buffered until their day is done, so anything reading state
            # has to close them first — otherwise a swap sees an empty projection and
            # seeds nothing.
            flush()
            # D15: the substitute is seeded from the source, never handed its state.
            src = uuid.UUID(row.payload["from_exercise_id"])
            dst = uuid.UUID(row.payload["to_exercise_id"])
            carried = out.get((row.user_id, src))
            if carried is not None:
                out[(row.user_id, dst)] = replace(carried, is_estimated=True)
            continue
        if row.type != "set_logged":
            # Stored, and meaningful to the fatigue gate, but not part of this projection.
            continue

        key = (row.user_id, uuid.UUID(row.payload["exercise_id"]))
        day = local_day(row.client_ts, row.user_tz)
        bucket = (*key, day)
        if bucket not in pending:
            pending[bucket] = []
            order.append(bucket)
        load = row.payload.get("load")
        pending[bucket].append(
            _Set(
                reps=int(row.payload["reps"]),
                rir=int(row.payload["rir"]),
                load=None if load is None else Decimal(str(load)),
                target_top=row.payload.get("target_top"),
                target_bottom=row.payload.get("target_bottom"),
                at=row.client_ts,
            )
        )

    flush()
    return out


def rebuild(conn: sa.Connection, user_id: uuid.UUID | None = None) -> int:
    """Drop the projection and rebuild it from the log. Never patches.

    Whole-table by default. A projection that can only be rebuilt for one user is a
    projection you cannot trust after a bad deploy.
    """
    where = [] if user_id is None else [events.c.user_id == user_id]
    conn.execute(
        sa.delete(exercise_state)
        if user_id is None
        else sa.delete(exercise_state).where(exercise_state.c.user_id == user_id)
    )
    rows = conn.execute(
        sa.select(events).where(*where).order_by(events.c.client_ts, events.c.id)
    ).all()
    folded = fold(rows)
    for (uid, exercise_id), state in folded.items():
        conn.execute(
            insert(exercise_state).values(
                user_id=uid, exercise_id=exercise_id,
                current_load=state.current_load, current_reps=state.current_reps,
                e1rm=state.e1rm,
                consecutive_successes=state.consecutive_successes,
                consecutive_failures=state.consecutive_failures,
                is_estimated=state.is_estimated,
                last_performed_at=state.last_performed_at,
            )
        )
    return len(folded)
