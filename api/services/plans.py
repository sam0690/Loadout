"""Plan generation: enqueue, poll, fetch.

Generation is the one thing slow enough to be worth a queue (PRD §6), so `POST /plans`
returns 202 with a job id and the client polls. Everything else in the API is synchronous.
"""

import uuid

import sqlalchemy as sa
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

from api.core.errors import NotFound
from api.repositories import plans as repo
from api.schemas.plans import Enqueued, JobStatus, PlanOut, PlanRequest
from worker.plan_job import generate


def request_plan(db: sa.Engine, q: Queue, user_id: uuid.UUID, body: PlanRequest) -> Enqueued:
    with db.connect() as conn:
        owned = repo.owns_context(conn, user_id, body.training_context_id)
    if not owned:
        raise NotFound("no such training context")

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


def job_status(q: Queue, user_id: uuid.UUID, job_id: str) -> JobStatus:
    try:
        job = Job.fetch(job_id, connection=q.connection)
    except NoSuchJobError:
        raise NotFound("no such job") from None
    # Someone else's job is 404, not 403, for the same reason a context is.
    if job.meta.get("user_id") != str(user_id):
        raise NotFound("no such job")

    plan_id = job.return_value() if job.is_finished else None
    if plan_id is not None:
        return JobStatus(job_id=job_id, status="finished", plan_id=uuid.UUID(plan_id))
    # Finished with no plan id (its result expired, or it returned nothing) is as useless
    # to the client as a failure, and was a 500.
    if job.is_failed or job.is_finished:
        return JobStatus(job_id=job_id, status="failed", error="plan generation failed")
    return JobStatus(job_id=job_id, status="started" if job.is_started else "queued")


def current_plan(db: sa.Engine, user_id: uuid.UUID) -> PlanOut:
    with db.connect() as conn:
        row = repo.latest(conn, user_id)
    if row is None:
        raise NotFound("no plan generated yet")
    return PlanOut(
        id=row.id, training_context_id=row.training_context_id, week_of=row.week_of,
        engine_version=row.engine_version, payload=row.payload,
    )
