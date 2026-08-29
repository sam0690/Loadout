"""Plan generation: enqueue, poll, fetch.

Generation is the one thing slow enough to be worth a queue (PRD §6), so `POST /plans`
returns 202 with a job id and the client polls. Everything else in the API is synchronous.
"""

import uuid
from datetime import date
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from redis import Redis
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

from api.auth import CurrentUser
from db import DATABASE_URL, redis_url
from engine.generator import Experience, Goal
from schema import plans, training_contexts
from worker.plan_job import generate

router = APIRouter(tags=["plans"])
_engine = sa.create_engine(DATABASE_URL)
_queue = Queue("plans", connection=Redis.from_url(redis_url()))

MAX_SESSIONS_PER_WEEK = 7


def engine() -> sa.Engine:
    return _engine


def queue() -> Queue:
    return _queue


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


@router.post("/plans", status_code=status.HTTP_202_ACCEPTED)
def request_plan(
    body: PlanRequest,
    user_id: CurrentUser,
    db: Annotated[sa.Engine, Depends(engine)],
    q: Annotated[Queue, Depends(queue)],
) -> Enqueued:
    with db.connect() as conn:
        owned = conn.execute(
            sa.select(training_contexts.c.id).where(
                training_contexts.c.id == body.training_context_id,
                training_contexts.c.user_id == user_id,
            )
        ).scalar_one_or_none()
    if owned is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such training context")

    job = q.enqueue(
        generate,
        str(user_id), str(body.training_context_id),
        [d.isoformat() for d in body.days],
        body.time_budget_minutes, body.experience.value, body.goal.value,
        # The caller is recorded on the job, not trusted from the URL: a job id is
        # guessable enough that polling must not leak someone else's plan.
        meta={"user_id": str(user_id)},
    )
    return Enqueued(job_id=job.id)


@router.get("/jobs/{job_id}")
def job_status(
    job_id: str, user_id: CurrentUser, q: Annotated[Queue, Depends(queue)]
) -> JobStatus:
    try:
        job = Job.fetch(job_id, connection=q.connection)
    except NoSuchJobError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such job") from None
    # Someone else's job is 404, not 403, for the same reason a context is.
    if job.meta.get("user_id") != str(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such job")

    if job.is_failed:
        return JobStatus(job_id=job_id, status="failed", error="plan generation failed")
    if job.is_finished:
        return JobStatus(job_id=job_id, status="finished", plan_id=uuid.UUID(job.return_value()))
    return JobStatus(job_id=job_id, status="started" if job.is_started else "queued")


@router.get("/plans/current")
def current_plan(
    user_id: CurrentUser, db: Annotated[sa.Engine, Depends(engine)]
) -> PlanOut:
    with db.connect() as conn:
        row = conn.execute(
            sa.select(plans)
            .where(plans.c.user_id == user_id)
            .order_by(plans.c.week_of.desc(), plans.c.generated_at.desc())
            .limit(1)
        ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no plan generated yet")
    return PlanOut(
        id=row.id, training_context_id=row.training_context_id, week_of=row.week_of,
        engine_version=row.engine_version, payload=row.payload,
    )
