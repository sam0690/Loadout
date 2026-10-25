import uuid

from fastapi import APIRouter, status

from api.deps import CurrentUser, Db
from api.schemas.contexts import ArchetypeOut, ContextIn, ContextOut
from api.services import contexts as service

router = APIRouter(prefix="/contexts", tags=["contexts"])


@router.get("/archetypes")
def list_archetypes(db: Db) -> list[ArchetypeOut]:
    """The presets onboarding offers.

    Unauthenticated on purpose: this is catalog data, and asking someone to sign in
    before they can see what the app even supports is friction for nothing (PRD §12).
    Ordered by size, so the leanest kit reads first — that is the launch cohort.
    """
    return service.list_archetypes(db)


@router.post("", status_code=status.HTTP_201_CREATED)
def create(body: ContextIn, user_id: CurrentUser, db: Db) -> ContextOut:
    return service.create(db, user_id, body)


@router.get("")
def list_contexts(user_id: CurrentUser, db: Db) -> list[ContextOut]:
    return service.list_contexts(db, user_id)


@router.get("/{context_id}")
def get_context(context_id: uuid.UUID, user_id: CurrentUser, db: Db) -> ContextOut:
    return service.get_context(db, user_id, context_id)


@router.put("/{context_id}")
def replace(context_id: uuid.UUID, body: ContextIn, user_id: CurrentUser, db: Db) -> ContextOut:
    return service.replace(db, user_id, context_id, body)


@router.delete("/{context_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(context_id: uuid.UUID, user_id: CurrentUser, db: Db) -> None:
    service.delete(db, user_id, context_id)
