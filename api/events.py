"""POST /events — batch ingest, idempotent on the client-generated id.

Constraint 3: the client generates the UUID and it is the idempotency key, so
`ON CONFLICT (id) DO NOTHING` makes a retry free. The server never assigns one.

This is the only route in 2.1; the rest of the API surface is 2.2.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.dialects.postgresql import insert

from api.deps import CurrentUser, get_engine
from projections.exercise_state import rebuild
from schema import EVENT_TYPES, events

router = APIRouter()

MAX_BATCH = 500


class Event(BaseModel):
    id: uuid.UUID
    type: Literal[EVENT_TYPES]  # type: ignore[valid-type]
    payload: dict[str, Any]
    client_ts: datetime
    user_tz: str

    @field_validator("user_tz")
    @classmethod
    def known_zone(cls, v: str) -> str:
        # Constraint 6: an IANA zone, validated at the boundary. A bad zone silently
        # shifts every "did I train today" answer for that user.
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"{v!r} is not an IANA timezone") from exc
        return v

    @field_validator("client_ts")
    @classmethod
    def tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("client_ts must carry an offset; never store naive local time")
        return v


# What each payload must carry for the projection and the fatigue gate to read it. Checked
# per event, so one malformed event is turned away on its own instead of failing the
# batch: a client retries a whole failed batch, so a single bad event used to block every
# good one queued behind it, forever. Extra keys are allowed (the client adds `slug`).
class _Payload(BaseModel):
    model_config = ConfigDict(extra="allow")


class SetLogged(_Payload):
    exercise_id: uuid.UUID
    reps: int = Field(ge=0, le=200)
    rir: int = Field(ge=0, le=10)
    load: Decimal | None = Field(default=None, ge=0, le=1000)
    target_bottom: int | None = None
    target_top: int | None = None


class ExerciseSwapped(_Payload):
    from_exercise_id: uuid.UUID
    to_exercise_id: uuid.UUID


class SessionClosed(_Payload):
    day: date
    sets_completed: int = Field(ge=0)


PAYLOADS: dict[str, type[_Payload]] = {
    "set_logged": SetLogged,
    "exercise_swapped": ExerciseSwapped,
    "workout_completed": SessionClosed,
    "workout_abandoned": SessionClosed,
    # feedback_submitted: nothing reads it until Phase 5, so its shape is not pinned yet.
}


class Rejected(BaseModel):
    id: uuid.UUID
    reason: str


class Batch(BaseModel):
    events: Annotated[list[Event], Field(min_length=1, max_length=MAX_BATCH)]


class Accepted(BaseModel):
    received: int
    stored: int  # smaller than received when a retry replayed events we already had
    projected: int
    # Turned away individually and not stored. The client stops resending these.
    rejected: list[Rejected] = []


@router.post("/events", response_model=Accepted)
def post_events(
    batch: Batch,
    # From the bearer token and nowhere else. This was a query parameter until 2.2a,
    # which meant anyone could write events attributed to anyone.
    user_id: CurrentUser,
    db: Annotated[sa.Engine, Depends(get_engine)],
) -> Accepted:
    if len({e.id for e in batch.events}) != len(batch.events):
        raise HTTPException(422, "duplicate event ids within one batch")

    rows, rejected = [], []
    for e in batch.events:
        shape = PAYLOADS.get(e.type)
        if shape is not None:
            try:
                shape.model_validate(e.payload)
            except ValidationError as exc:
                rejected.append(Rejected(id=e.id, reason=_first_error(exc)))
                continue
        rows.append({
            "id": e.id, "user_id": user_id, "type": e.type, "payload": e.payload,
            "client_ts": e.client_ts, "user_tz": e.user_tz,
        })

    if not rows:
        return Accepted(received=len(batch.events), stored=0, projected=0, rejected=rejected)

    with db.begin() as conn:
        # RETURNING rather than rowcount: a multi-values INSERT reports -1, and the
        # count of rows that actually landed is the whole signal a client needs to know
        # its retry was absorbed.
        stored = len(
            conn.execute(
                insert(events)
                .values(rows)
                .on_conflict_do_nothing(index_elements=["id"])
                .returning(events.c.id)
            ).all()
        )
        # Microseconds of arithmetic, so it runs in the request rather than a job
        # (PRD §6, logging a set).
        projected = rebuild(conn, user_id)
    return Accepted(
        received=len(batch.events), stored=stored, projected=projected, rejected=rejected
    )


class StoredEvent(Event):
    server_ts: datetime


# ponytail: the whole log in one response. A year of training is a few thousand sets,
# well under a megabyte; page it (after a client_ts cursor) when a log outgrows that.
@router.get("/events")
def list_events(
    user_id: CurrentUser, db: Annotated[sa.Engine, Depends(get_engine)]
) -> list[StoredEvent]:
    """The caller's own log, oldest first, so a new device can rebuild its history.

    The device keeps its own copy for offline, but that copy started empty on a new phone
    or after cleared storage, and history, progress and PRs all read from it.
    """
    with db.connect() as conn:
        rows = conn.execute(
            sa.select(events)
            .where(events.c.user_id == user_id)
            .order_by(events.c.client_ts, events.c.id)
        ).all()
    return [
        StoredEvent(
            id=r.id, type=r.type, payload=r.payload, client_ts=r.client_ts,
            user_tz=r.user_tz, server_ts=r.server_ts,
        )
        for r in rows
    ]


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    where = ".".join(str(p) for p in err["loc"]) or "payload"
    return f"{where}: {err['msg']}"
