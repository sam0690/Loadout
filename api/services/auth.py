"""Magic-link and password auth. No passwords required (build prompt 2.2), allowed (D31).

Two halves with different storage models, on purpose. The **link** is stateful, because
single-use is the property that matters and a self-contained token cannot express it. The
**session** is a stateless JWT (D23), which buys no per-request database hit at the cost
of no revocation.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from api.core.errors import Conflict, Unauthorized
from api.core.security import (
    DECOY,
    LINK_TTL,
    encode_session,
    hash_password,
    hash_token,
    new_link_token,
    password_matches,
)
from api.repositories import auth as repo
from api.schemas.auth import PROFILE_FIELDS, Me, Profile, Session

log = logging.getLogger("loadout.auth")

BASE_URL = "http://localhost:3000"
# Unconsumed links outstanding before we stop issuing more. Counted in the database
# rather than in memory, so it holds across worker processes without new infrastructure.
# Consumed links do not count: logging in three times in a quarter hour is fine, being
# mailed three unused links is the thing worth stopping.
MAX_OUTSTANDING_LINKS = 3


def send_link(email: str, url: str) -> None:
    """Deliver the magic link.

    Writes it to the log for now. Swapping the body for an HTTP call to a provider is the
    whole change at launch — there is deliberately no adapter or interface here, because
    an abstraction with one implementation is the thing CLAUDE.md forbids.
    """
    log.info("magic_link email=%s url=%s", email, url)


def issue_session(user_id: uuid.UUID, now: datetime) -> Session:
    token, expires = encode_session(user_id, now)
    return Session(access_token=token, expires_at=expires)


def issue_token(conn: sa.Connection, user_id: uuid.UUID, now: datetime) -> str:
    token = new_link_token()
    repo.insert_link(conn, hash_token(token), user_id, now + LINK_TTL)
    return token


def request_link(db: sa.Engine, email: str, now: datetime) -> None:
    """Send a login link, creating the account on first use. Silent on every outcome."""
    email = email.strip()
    with db.begin() as conn:
        user_id = repo.user_id_by_email(conn, email)
        if user_id is None:
            user_id = uuid.uuid4()
            if not repo.insert_user(conn, user_id, email):
                # A concurrent request created it between the lookup and the insert.
                user_id = repo.user_id_by_email(conn, email)
                assert user_id is not None
        if repo.count_outstanding_links(conn, user_id, now) >= MAX_OUTSTANDING_LINKS:
            # Same 202, same body. Answering differently here would turn the rate limit
            # into the enumeration oracle the endpoint was written to avoid, and would
            # tell an attacker exactly when their target had unread mail.
            log.warning("magic_link_throttled user_id=%s", user_id)
            return
        token = issue_token(conn, user_id, now)
    # Onboarding is the page that reads ?token= and signs in; /auth/verify is the API
    # call it makes, not a page, and a link pointing there opened a 404.
    send_link(email, f"{BASE_URL}/onboarding?token={token}")


def verify(db: sa.Engine, token: str, now: datetime) -> Session:
    with db.begin() as conn:
        user_id = repo.consume_link(conn, hash_token(token), now)
    # Unknown, expired and already-used all answer the same way: a caller probing
    # tokens learns only that this one did not work.
    if user_id is None:
        raise Unauthorized("invalid or expired link")
    return issue_session(user_id, now)


def signup(db: sa.Engine, email: str, password: str, now: datetime) -> Session:
    email = email.strip()
    user_id = uuid.uuid4()
    with db.begin() as conn:
        if not repo.insert_user(conn, user_id, email, hash_password(password)):
            raise Conflict("an account with that email already exists")
    return issue_session(user_id, now)


def login(db: sa.Engine, email: str, password: str, now: datetime) -> Session:
    with db.connect() as conn:
        row = repo.credentials_by_email(conn, email.strip())
    stored = row.password_hash if row is not None and row.password_hash else DECOY
    if not password_matches(password, stored) or row is None or not row.password_hash:
        raise Unauthorized("wrong email or password")
    return issue_session(row.id, now)


def me(db: sa.Engine, user_id: uuid.UUID) -> Me:
    with db.connect() as conn:
        row = repo.get_user(conn, user_id)
    if row is None:
        raise Unauthorized("no such user")
    return Me(id=row.id, email=row.email, created_at=row.created_at)


def _profile(row: sa.Row[tuple[object, ...]]) -> Profile:
    return Profile(**{f: getattr(row, f) for f in PROFILE_FIELDS})


def read_profile(db: sa.Engine, user_id: uuid.UUID) -> Profile:
    with db.connect() as conn:
        row = repo.get_user(conn, user_id)
    if row is None:
        raise Unauthorized("no such user")
    return _profile(row)


def write_profile(db: sa.Engine, user_id: uuid.UUID, values: dict[str, Any]) -> Profile:
    with db.begin() as conn:
        if not repo.user_exists(conn, user_id):
            raise Unauthorized("no such user")
        if values:
            repo.update_user(conn, user_id, values)
        row = repo.get_user(conn, user_id)
        assert row is not None
        return _profile(row)
