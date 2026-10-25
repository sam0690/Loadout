import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schema import EVENT_TYPES

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
class Payload(BaseModel):
    model_config = ConfigDict(extra="allow")


class SetLogged(Payload):
    exercise_id: uuid.UUID
    reps: int = Field(ge=0, le=200)
    rir: int = Field(ge=0, le=10)
    load: Decimal | None = Field(default=None, ge=0, le=1000)
    target_bottom: int | None = None
    target_top: int | None = None


class ExerciseSwapped(Payload):
    from_exercise_id: uuid.UUID
    to_exercise_id: uuid.UUID


class SessionClosed(Payload):
    day: date
    sets_completed: int = Field(ge=0)


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


class StoredEvent(Event):
    server_ts: datetime
