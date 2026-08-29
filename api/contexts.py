"""Training contexts CRUD.

Equipment belongs to a context, not to a user (CLAUDE.md constraint 5). This is the API
over that, including the per-context load overrides from D21 that nothing has exercised
through HTTP yet.

The wire format speaks equipment *slugs*, not uuids: a client says "dumbbells", and every
slug resolves through the alias table (0.2) or is refused. Resolution of what a context
actually contains reuses `queries/context_loads.sql` rather than reimplementing D10.
"""

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert

from api.auth import CurrentUser
from db import DATABASE_URL
from ingest.equipment import UnknownEquipment, resolve_slug
from schema import equipment, gym_archetypes, training_context_loads, training_contexts

router = APIRouter(prefix="/contexts", tags=["contexts"])
_engine = sa.create_engine(DATABASE_URL)
CONTEXT_LOADS = (
    Path(__file__).resolve().parent.parent / "queries" / "context_loads.sql"
).read_text()


def engine() -> sa.Engine:
    return _engine


class Loads(BaseModel):
    """A context's own answer for one piece of equipment (D21). Absent means the catalog
    default stands, which is not the same as 'not loadable'."""

    load_increments: list[Decimal] | None = None
    bar_weight: Decimal | None = None


class ContextIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    archetype_slug: str | None = None
    equipment_added: list[str] = []
    equipment_removed: list[str] = []
    is_default: bool = False
    loads: dict[str, Loads] = {}


class ResolvedEquipment(BaseModel):
    slug: str
    equipment_class: str
    is_fixed_path: bool
    load_increments: list[Decimal] | None
    bar_weight: Decimal | None


class ContextOut(BaseModel):
    id: uuid.UUID
    label: str
    archetype_slug: str | None
    is_default: bool
    equipment: list[ResolvedEquipment]


def _equipment_ids(conn: sa.Connection, slugs: list[str]) -> list[uuid.UUID]:
    """Slug or brand alias to canonical id, refusing anything unrecognised.

    Reuses 0.2's resolver so the API and the ingest cannot drift on what a name means.
    """
    out = []
    for raw in slugs:
        try:
            canonical = resolve_slug(conn, raw)
        except UnknownEquipment as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        out.append(
            conn.execute(
                sa.select(equipment.c.id).where(equipment.c.slug == canonical)
            ).scalar_one()
        )
    return out


def _archetype_id(conn: sa.Connection, slug: str | None) -> uuid.UUID | None:
    if slug is None:
        return None
    found: uuid.UUID | None = conn.execute(
        sa.select(gym_archetypes.c.id).where(gym_archetypes.c.slug == slug)
    ).scalar_one_or_none()
    if found is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"no archetype {slug!r}")
    return found


def _owned(conn: sa.Connection, context_id: uuid.UUID, user_id: uuid.UUID) -> sa.Row[Any]:
    row = conn.execute(
        sa.select(training_contexts).where(
            training_contexts.c.id == context_id,
            # Ownership is part of the lookup, not a check after it. Someone else's
            # context is 404 rather than 403: a 403 confirms the id exists.
            training_contexts.c.user_id == user_id,
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such training context")
    return row


def _write_loads(
    conn: sa.Connection, context_id: uuid.UUID, loads: dict[str, Loads]
) -> None:
    conn.execute(
        sa.delete(training_context_loads).where(
            training_context_loads.c.training_context_id == context_id
        )
    )
    for raw, spec in loads.items():
        if spec.load_increments is None and spec.bar_weight is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"loads for {raw!r} say nothing; omit the entry to use the catalog default",
            )
        if spec.load_increments is not None and list(spec.load_increments) != sorted(
            spec.load_increments
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"load_increments for {raw!r} must be sorted ascending",
            )
        (eq_id,) = _equipment_ids(conn, [raw])
        conn.execute(
            insert(training_context_loads).values(
                training_context_id=context_id, equipment_id=eq_id,
                load_increments=spec.load_increments, bar_weight=spec.bar_weight,
            )
        )


def _render(conn: sa.Connection, row: sa.Row[Any]) -> ContextOut:
    resolved = conn.execute(
        sa.text(CONTEXT_LOADS), {"training_context_id": row.id}
    ).all()
    archetype = (
        conn.execute(
            sa.select(gym_archetypes.c.slug).where(gym_archetypes.c.id == row.archetype_id)
        ).scalar_one_or_none()
        if row.archetype_id
        else None
    )
    return ContextOut(
        id=row.id, label=row.label, archetype_slug=archetype, is_default=row.is_default,
        equipment=[
            ResolvedEquipment(
                slug=r.slug, equipment_class=r._mapping["class"], is_fixed_path=r.is_fixed_path,
                load_increments=r.load_increments, bar_weight=r.bar_weight,
            )
            for r in resolved
        ],
    )


def _clear_other_defaults(
    conn: sa.Connection, user_id: uuid.UUID, keep: uuid.UUID | None
) -> None:
    """The database allows one default per user, so demote the old one first."""
    stmt = sa.update(training_contexts).where(
        training_contexts.c.user_id == user_id, training_contexts.c.is_default.is_(True)
    )
    if keep is not None:
        stmt = stmt.where(training_contexts.c.id != keep)
    conn.execute(stmt.values(is_default=False))


@router.post("", status_code=status.HTTP_201_CREATED)
def create(
    body: ContextIn, user_id: CurrentUser, db: Annotated[sa.Engine, Depends(engine)]
) -> ContextOut:
    context_id = uuid.uuid4()
    with db.begin() as conn:
        # The first context a user creates is their default whatever they asked for:
        # a user with contexts but no default has no session to start.
        has_any = conn.execute(
            sa.select(sa.func.count())
            .select_from(training_contexts)
            .where(training_contexts.c.user_id == user_id)
        ).scalar_one()
        is_default = body.is_default or has_any == 0
        if is_default:
            _clear_other_defaults(conn, user_id, keep=None)
        conn.execute(
            sa.insert(training_contexts).values(
                id=context_id, user_id=user_id, label=body.label,
                archetype_id=_archetype_id(conn, body.archetype_slug),
                equipment_added=_equipment_ids(conn, body.equipment_added),
                equipment_removed=_equipment_ids(conn, body.equipment_removed),
                is_default=is_default,
            )
        )
        _write_loads(conn, context_id, body.loads)
        return _render(conn, _owned(conn, context_id, user_id))


@router.get("")
def list_contexts(
    user_id: CurrentUser, db: Annotated[sa.Engine, Depends(engine)]
) -> list[ContextOut]:
    with db.connect() as conn:
        rows = conn.execute(
            sa.select(training_contexts)
            .where(training_contexts.c.user_id == user_id)
            .order_by(training_contexts.c.is_default.desc(), training_contexts.c.label)
        ).all()
        return [_render(conn, r) for r in rows]


@router.get("/{context_id}")
def get_context(
    context_id: uuid.UUID, user_id: CurrentUser, db: Annotated[sa.Engine, Depends(engine)]
) -> ContextOut:
    with db.connect() as conn:
        return _render(conn, _owned(conn, context_id, user_id))


@router.put("/{context_id}")
def replace(
    context_id: uuid.UUID, body: ContextIn, user_id: CurrentUser,
    db: Annotated[sa.Engine, Depends(engine)],
) -> ContextOut:
    with db.begin() as conn:
        _owned(conn, context_id, user_id)
        if body.is_default:
            _clear_other_defaults(conn, user_id, keep=context_id)
        conn.execute(
            sa.update(training_contexts)
            .where(training_contexts.c.id == context_id)
            .values(
                label=body.label,
                archetype_id=_archetype_id(conn, body.archetype_slug),
                equipment_added=_equipment_ids(conn, body.equipment_added),
                equipment_removed=_equipment_ids(conn, body.equipment_removed),
                is_default=body.is_default,
            )
        )
        _write_loads(conn, context_id, body.loads)
        return _render(conn, _owned(conn, context_id, user_id))


@router.delete("/{context_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    context_id: uuid.UUID, user_id: CurrentUser, db: Annotated[sa.Engine, Depends(engine)]
) -> None:
    with db.begin() as conn:
        row = _owned(conn, context_id, user_id)
        conn.execute(sa.delete(training_contexts).where(training_contexts.c.id == context_id))
        if row.is_default:
            # Promote something, so the user is never left with contexts and no default.
            successor = conn.execute(
                sa.select(training_contexts.c.id)
                .where(training_contexts.c.user_id == user_id)
                .order_by(training_contexts.c.label)
                .limit(1)
            ).scalar_one_or_none()
            if successor is not None:
                conn.execute(
                    sa.update(training_contexts)
                    .where(training_contexts.c.id == successor)
                    .values(is_default=True)
                )
