"""POST /events — batch ingest, idempotent on the client-generated id.

Constraint 3: the client generates the UUID and it is the idempotency key, so
`ON CONFLICT (id) DO NOTHING` makes a retry free. The server never assigns one.

This is the only route in 2.1; the rest of the API surface is 2.2.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.dialects.postgresql import insert

from db import DATABASE_URL
from projections.exercise_state import rebuild
from schema import EVENT_TYPES, events

router = APIRouter()
_engine = sa.create_engine(DATABASE_URL)

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


class Batch(BaseModel):
    events: Annotated[list[Event], Field(min_length=1, max_length=MAX_BATCH)]


class Accepted(BaseModel):
    received: int
    stored: int  # smaller than received when a retry replayed events we already had
    projected: int


def engine() -> sa.Engine:
    return _engine


@router.post("/events", response_model=Accepted)
def post_events(
    batch: Batch,
    user_id: uuid.UUID,
    db: Annotated[sa.Engine, Depends(engine)],
) -> Accepted:
    rows = [
        {
            "id": e.id, "user_id": user_id, "type": e.type, "payload": e.payload,
            "client_ts": e.client_ts, "user_tz": e.user_tz,
        }
        for e in batch.events
    ]
    if len({r["id"] for r in rows}) != len(rows):
        raise HTTPException(422, "duplicate event ids within one batch")

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
    return Accepted(received=len(rows), stored=stored, projected=projected)
