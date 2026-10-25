"""Training contexts CRUD.

Equipment belongs to a context, not to a user (CLAUDE.md constraint 5). This is the API
over that, including the per-context load overrides from D21.

The wire format speaks equipment *slugs*, not uuids: a client says "dumbbells", and every
slug resolves through the alias table (0.2) or is refused. Resolution of what a context
actually contains reuses `queries/context_loads.sql` rather than reimplementing D10.
"""

import uuid
from typing import Any

import sqlalchemy as sa

from api.core.errors import Invalid, NotFound
from api.repositories import contexts as repo
from api.schemas.contexts import ArchetypeOut, ContextIn, ContextOut, Loads, ResolvedEquipment
from ingest.equipment import UnknownEquipment


def _equipment_ids(conn: sa.Connection, slugs: list[str]) -> list[uuid.UUID]:
    out = []
    for raw in slugs:
        try:
            out.append(repo.equipment_id(conn, raw))
        except UnknownEquipment as exc:
            raise Invalid(str(exc)) from exc
    return out


def _archetype_id(conn: sa.Connection, slug: str | None) -> uuid.UUID | None:
    if slug is None:
        return None
    found = repo.archetype_id(conn, slug)
    if found is None:
        raise Invalid(f"no archetype {slug!r}")
    return found


def _owned(conn: sa.Connection, context_id: uuid.UUID, user_id: uuid.UUID) -> sa.Row[Any]:
    row = repo.owned(conn, context_id, user_id)
    # Someone else's context is 404 rather than 403: a 403 confirms the id exists.
    if row is None:
        raise NotFound("no such training context")
    return row


def _write_loads(conn: sa.Connection, context_id: uuid.UUID, loads: dict[str, Loads]) -> None:
    repo.delete_loads(conn, context_id)
    for raw, spec in loads.items():
        if spec.load_increments is None and spec.bar_weight is None:
            raise Invalid(
                f"loads for {raw!r} say nothing; omit the entry to use the catalog default"
            )
        if spec.load_increments is not None and list(spec.load_increments) != sorted(
            spec.load_increments
        ):
            raise Invalid(f"load_increments for {raw!r} must be sorted ascending")
        (eq_id,) = _equipment_ids(conn, [raw])
        repo.insert_load(conn, context_id, eq_id, spec.load_increments, spec.bar_weight)


def _render(conn: sa.Connection, row: sa.Row[Any]) -> ContextOut:
    resolved = repo.resolved_equipment(conn, row.id)
    archetype = repo.archetype_slug(conn, row.archetype_id) if row.archetype_id else None
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


def _columns(conn: sa.Connection, body: ContextIn) -> dict[str, Any]:
    return {
        "label": body.label,
        "archetype_id": _archetype_id(conn, body.archetype_slug),
        "equipment_added": _equipment_ids(conn, body.equipment_added),
        "equipment_removed": _equipment_ids(conn, body.equipment_removed),
    }


def list_archetypes(db: sa.Engine) -> list[ArchetypeOut]:
    with db.connect() as conn:
        rows = repo.archetypes(conn)
        slugs = repo.equipment_slugs(conn)
    return [
        ArchetypeOut(
            slug=r.slug,
            name=r.name,
            equipment=sorted(slugs[eid] for eid in r.equipment_ids if eid in slugs),
        )
        for r in rows
    ]


def create(db: sa.Engine, user_id: uuid.UUID, body: ContextIn) -> ContextOut:
    context_id = uuid.uuid4()
    with db.begin() as conn:
        # The first context a user creates is their default whatever they asked for:
        # a user with contexts but no default has no session to start.
        is_default = body.is_default or repo.count_for_user(conn, user_id) == 0
        if is_default:
            repo.clear_other_defaults(conn, user_id, keep=None)
        repo.insert_context(
            conn,
            {"id": context_id, "user_id": user_id, **_columns(conn, body),
             "is_default": is_default},
        )
        _write_loads(conn, context_id, body.loads)
        return _render(conn, _owned(conn, context_id, user_id))


def list_contexts(db: sa.Engine, user_id: uuid.UUID) -> list[ContextOut]:
    with db.connect() as conn:
        return [_render(conn, r) for r in repo.for_user(conn, user_id)]


def get_context(db: sa.Engine, user_id: uuid.UUID, context_id: uuid.UUID) -> ContextOut:
    with db.connect() as conn:
        return _render(conn, _owned(conn, context_id, user_id))


def replace(
    db: sa.Engine, user_id: uuid.UUID, context_id: uuid.UUID, body: ContextIn
) -> ContextOut:
    with db.begin() as conn:
        _owned(conn, context_id, user_id)
        if body.is_default:
            repo.clear_other_defaults(conn, user_id, keep=context_id)
        repo.update_context(
            conn, context_id, {**_columns(conn, body), "is_default": body.is_default}
        )
        _write_loads(conn, context_id, body.loads)
        return _render(conn, _owned(conn, context_id, user_id))


def delete(db: sa.Engine, user_id: uuid.UUID, context_id: uuid.UUID) -> None:
    with db.begin() as conn:
        row = _owned(conn, context_id, user_id)
        repo.delete_context(conn, context_id)
        if row.is_default:
            # Promote something, so the user is never left with contexts and no default.
            successor = repo.first_by_label(conn, user_id)
            if successor is not None:
                repo.make_default(conn, successor)
