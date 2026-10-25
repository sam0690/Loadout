from fastapi import APIRouter

from api.deps import CurrentUser, Db
from api.schemas.events import Accepted, Batch, StoredEvent
from api.services import events as service

router = APIRouter()


@router.post("/events", response_model=Accepted)
def post_events(
    batch: Batch,
    # From the bearer token and nowhere else. This was a query parameter until 2.2a,
    # which meant anyone could write events attributed to anyone.
    user_id: CurrentUser,
    db: Db,
) -> Accepted:
    return service.ingest(db, user_id, batch)


# ponytail: the whole log in one response. A year of training is a few thousand sets,
# well under a megabyte; page it (after a client_ts cursor) when a log outgrows that.
@router.get("/events")
def list_events(user_id: CurrentUser, db: Db) -> list[StoredEvent]:
    """The caller's own log, oldest first, so a new device can rebuild its history.

    The device keeps its own copy for offline, but that copy started empty on a new phone
    or after cleared storage, and history, progress and PRs all read from it.
    """
    return service.history(db, user_id)
