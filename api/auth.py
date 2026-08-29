"""Magic-link auth. No passwords (build prompt 2.2).

Two halves with different storage models, on purpose. The **link** is stateful, because
single-use is the property that matters and a self-contained token cannot express it. The
**session** is a stateless JWT (D23), which buys no per-request database hit at the cost
of no revocation.
"""

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr

from db import DATABASE_URL, jwt_secret
from schema import magic_links, users

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("loadout.auth")
_engine = sa.create_engine(DATABASE_URL)
_bearer = HTTPBearer(auto_error=False)

ALGORITHM = "HS256"
LINK_TTL = timedelta(minutes=15)
# No revocation exists (D23), so the window a leaked token stays usable is exactly this.
SESSION_TTL = timedelta(days=7)
BASE_URL = "http://localhost:3000"
# Unconsumed links outstanding before we stop issuing more. Counted in the database
# rather than in memory, so it holds across worker processes without new infrastructure.
# Consumed links do not count: logging in three times in a quarter hour is fine, being
# mailed three unused links is the thing worth stopping.
MAX_OUTSTANDING_LINKS = 3


# One body for every outcome of /auth/request: new account, known account, throttled.
ACCEPTED = {"detail": "If that address can receive mail, a link is on its way."}


class RequestLink(BaseModel):
    email: EmailStr


class Verify(BaseModel):
    token: str


class Session(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class Me(BaseModel):
    id: uuid.UUID
    email: str


def engine() -> sa.Engine:
    return _engine


def hash_token(token: str) -> str:
    """Only the hash is stored, so a leaked database hands out no logins."""
    return hashlib.sha256(token.encode()).hexdigest()


def send_link(email: str, url: str) -> None:
    """Deliver the magic link.

    Writes it to the log for now. Swapping the body for an HTTP call to a provider is the
    whole change at launch — there is deliberately no adapter or interface here, because
    an abstraction with one implementation is the thing CLAUDE.md forbids.
    """
    log.info("magic_link email=%s url=%s", email, url)


def issue_token(conn: sa.Connection, user_id: uuid.UUID) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        sa.insert(magic_links).values(
            token_hash=hash_token(token),
            user_id=user_id,
            expires_at=datetime.now(UTC) + LINK_TTL,
        )
    )
    return token


@router.post("/request", status_code=status.HTTP_202_ACCEPTED)
def request_link(body: RequestLink, db: Annotated[sa.Engine, Depends(engine)]) -> dict[str, str]:
    """Send a login link. Creates the account on first use.

    The response is identical whether or not the address is known. A different status or
    body for an unknown email is a user-enumeration oracle, and this endpoint is
    unauthenticated by definition.
    """
    email = body.email.strip()
    with db.begin() as conn:
        user_id = conn.execute(
            sa.select(users.c.id).where(sa.func.lower(users.c.email) == email.lower())
        ).scalar_one_or_none()
        if user_id is None:
            user_id = uuid.uuid4()
            conn.execute(sa.insert(users).values(id=user_id, email=email))
        outstanding = conn.execute(
            sa.select(sa.func.count())
            .select_from(magic_links)
            .where(
                magic_links.c.user_id == user_id,
                magic_links.c.consumed_at.is_(None),
                magic_links.c.expires_at > datetime.now(UTC),
            )
        ).scalar_one()
        if outstanding >= MAX_OUTSTANDING_LINKS:
            # Same 202, same body. Answering differently here would turn the rate limit
            # into the enumeration oracle the endpoint was written to avoid, and would
            # tell an attacker exactly when their target had unread mail.
            log.warning("magic_link_throttled user_id=%s", user_id)
            return ACCEPTED
        token = issue_token(conn, user_id)
    send_link(email, f"{BASE_URL}/auth/verify?token={token}")
    return ACCEPTED


@router.post("/verify")
def verify(body: Verify, db: Annotated[sa.Engine, Depends(engine)]) -> Session:
    now = datetime.now(UTC)
    with db.begin() as conn:
        row = conn.execute(
            sa.select(magic_links).where(magic_links.c.token_hash == hash_token(body.token))
        ).one_or_none()
        # Unknown, expired and already-used all answer the same way: a caller probing
        # tokens learns only that this one did not work.
        if row is None or row.consumed_at is not None or row.expires_at <= now:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired link")
        conn.execute(
            sa.update(magic_links)
            .where(magic_links.c.token_hash == row.token_hash)
            .values(consumed_at=now)
        )
    expires = now + SESSION_TTL
    claims = {"sub": str(row.user_id), "iat": int(now.timestamp()), "exp": int(expires.timestamp())}
    return Session(access_token=jwt.encode(claims, jwt_secret(), ALGORITHM), expires_at=expires)


def current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> uuid.UUID:
    """The caller's id, from the bearer token and nowhere else.

    Before this existed, POST /events took user_id as a query parameter, so anyone could
    write events as anyone. The whole fix is that this is the only source of a user id.
    """
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        claims = jwt.decode(
            creds.credentials,
            jwt_secret(),
            algorithms=[ALGORITHM],
            # A token without an expiry never expires, so its absence is a rejection
            # rather than a default.
            options={"require": ["sub", "exp", "iat"]},
        )
        return uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc


CurrentUser = Annotated[uuid.UUID, Depends(current_user)]


@router.get("/me")
def me(user_id: CurrentUser, db: Annotated[sa.Engine, Depends(engine)]) -> Me:
    with db.connect() as conn:
        row = conn.execute(sa.select(users).where(users.c.id == user_id)).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no such user")
    return Me(id=row.id, email=row.email)
