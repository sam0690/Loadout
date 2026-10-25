import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from schema import magic_links, users


def user_id_by_email(conn: sa.Connection, email: str) -> uuid.UUID | None:
    found: uuid.UUID | None = conn.execute(
        sa.select(users.c.id).where(sa.func.lower(users.c.email) == email.lower())
    ).scalar_one_or_none()
    return found


def credentials_by_email(conn: sa.Connection, email: str) -> sa.Row[Any] | None:
    return conn.execute(
        sa.select(users.c.id, users.c.password_hash).where(
            sa.func.lower(users.c.email) == email.lower()
        )
    ).one_or_none()


def insert_user(
    conn: sa.Connection, user_id: uuid.UUID, email: str, password_hash: str | None = None
) -> None:
    conn.execute(sa.insert(users).values(id=user_id, email=email, password_hash=password_hash))


def get_user(conn: sa.Connection, user_id: uuid.UUID) -> sa.Row[Any] | None:
    return conn.execute(sa.select(users).where(users.c.id == user_id)).one_or_none()


def user_exists(conn: sa.Connection, user_id: uuid.UUID) -> bool:
    found = conn.execute(sa.select(users.c.id).where(users.c.id == user_id)).one_or_none()
    return found is not None


def update_user(conn: sa.Connection, user_id: uuid.UUID, values: dict[str, Any]) -> None:
    conn.execute(sa.update(users).where(users.c.id == user_id).values(**values))


def count_outstanding_links(conn: sa.Connection, user_id: uuid.UUID, now: datetime) -> int:
    count: int = conn.execute(
        sa.select(sa.func.count())
        .select_from(magic_links)
        .where(
            magic_links.c.user_id == user_id,
            magic_links.c.consumed_at.is_(None),
            magic_links.c.expires_at > now,
        )
    ).scalar_one()
    return count


def insert_link(
    conn: sa.Connection, token_hash: str, user_id: uuid.UUID, expires_at: datetime
) -> None:
    conn.execute(
        sa.insert(magic_links).values(
            token_hash=token_hash, user_id=user_id, expires_at=expires_at
        )
    )


def get_link(conn: sa.Connection, token_hash: str) -> sa.Row[Any] | None:
    return conn.execute(
        sa.select(magic_links).where(magic_links.c.token_hash == token_hash)
    ).one_or_none()


def consume_link(conn: sa.Connection, token_hash: str, now: datetime) -> None:
    conn.execute(
        sa.update(magic_links)
        .where(magic_links.c.token_hash == token_hash)
        .values(consumed_at=now)
    )
