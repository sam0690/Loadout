"""Batch ingest, idempotent on the client-generated id.

Constraint 3: the client generates the UUID and it is the idempotency key, so
`ON CONFLICT (id) DO NOTHING` makes a retry free. The server never assigns one.
"""

import uuid
from typing import Any

import sqlalchemy as sa
from pydantic import ValidationError

from api.core.errors import Invalid
from api.repositories import events as repo
from api.schemas.events import (
    Accepted,
    Batch,
    ExerciseSwapped,
    Payload,
    Rejected,
    SessionClosed,
    SetLogged,
    StoredEvent,
)
from projections.exercise_state import rebuild

PAYLOADS: dict[str, type[Payload]] = {
    "set_logged": SetLogged,
    "exercise_swapped": ExerciseSwapped,
    "workout_completed": SessionClosed,
    "workout_abandoned": SessionClosed,
    # feedback_submitted: nothing reads it until Phase 5, so its shape is not pinned yet.
}


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    where = ".".join(str(p) for p in err["loc"]) or "payload"
    return f"{where}: {err['msg']}"


def ingest(db: sa.Engine, user_id: uuid.UUID, batch: Batch) -> Accepted:
    if len({e.id for e in batch.events}) != len(batch.events):
        raise Invalid("duplicate event ids within one batch")

    rows: list[dict[str, Any]] = []
    rejected: list[Rejected] = []
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
        stored = repo.append(conn, rows)
        # Microseconds of arithmetic, so it runs in the request rather than a job
        # (PRD §6, logging a set).
        projected = rebuild(conn, user_id)
    return Accepted(
        received=len(batch.events), stored=stored, projected=projected, rejected=rejected
    )


def history(db: sa.Engine, user_id: uuid.UUID) -> list[StoredEvent]:
    with db.connect() as conn:
        rows = repo.for_user(conn, user_id)
    return [
        StoredEvent(
            id=r.id, type=r.type, payload=r.payload, client_ts=r.client_ts,
            user_tz=r.user_tz, server_ts=r.server_ts,
        )
        for r in rows
    ]
