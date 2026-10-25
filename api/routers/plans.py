from fastapi import APIRouter, status

from api.deps import RQ, CurrentUser, Db
from api.schemas.plans import Enqueued, JobStatus, PlanOut, PlanRequest
from api.services import plans as service

router = APIRouter(tags=["plans"])


@router.post("/plans", status_code=status.HTTP_202_ACCEPTED)
def request_plan(body: PlanRequest, user_id: CurrentUser, db: Db, q: RQ) -> Enqueued:
    return service.request_plan(db, q, user_id, body)


@router.get("/jobs/{job_id}")
def job_status(job_id: str, user_id: CurrentUser, q: RQ) -> JobStatus:
    return service.job_status(q, user_id, job_id)


@router.get("/plans/current")
def current_plan(user_id: CurrentUser, db: Db) -> PlanOut:
    return service.current_plan(db, user_id)
