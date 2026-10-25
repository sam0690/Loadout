import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from engine.generator import Experience, Goal

MAX_SESSIONS_PER_WEEK = 7


class PlanRequest(BaseModel):
    training_context_id: uuid.UUID
    # Calendar dates in the user's own zone, resolved by the client. The engine has no
    # clock, and "no muscle hard on consecutive days" (D14) needs real dates rather than
    # a session count -- Mon/Wed/Fri and Mon/Tue/Wed are not the same week.
    days: list[date] = Field(min_length=1, max_length=MAX_SESSIONS_PER_WEEK)
    time_budget_minutes: int = Field(ge=0, le=300)
    experience: Experience = Experience.INTERMEDIATE
    goal: Goal = Goal.HYPERTROPHY

    @field_validator("days")
    @classmethod
    def one_week(cls, v: list[date]) -> list[date]:
        if len({(d.isocalendar().year, d.isocalendar().week) for d in v}) != 1:
            raise ValueError("all days must fall in the same ISO week")
        if len(set(v)) != len(v):
            raise ValueError("duplicate days")
        return sorted(v)


class Enqueued(BaseModel):
    job_id: str


class JobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "started", "finished", "failed"]
    plan_id: uuid.UUID | None = None
    error: str | None = None


class PlanOut(BaseModel):
    id: uuid.UUID
    training_context_id: uuid.UUID
    week_of: date
    engine_version: str
    payload: dict[str, Any]
