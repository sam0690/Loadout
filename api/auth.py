"""Magic-link auth. No passwords (build prompt 2.2).

Two halves with different storage models, on purpose. The **link** is stateful, because
single-use is the property that matters and a self-contained token cannot express it. The
**session** is a stateless JWT (D23), which buys no per-request database hit at the cost
of no revocation.
"""

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated

import jwt
import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field, StringConstraints

from db import DATABASE_URL, jwt_secret
from engine.generator import Experience, Goal
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


class Credentials(BaseModel):
    email: EmailStr
    # The ceiling stops a megabyte "password" from buying a megabyte of scrypt work.
    password: str = Field(min_length=8, max_length=256)


class Verify(BaseModel):
    token: str


class Session(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class Me(BaseModel):
    id: uuid.UUID
    email: str
    created_at: datetime


class Profile(BaseModel):
    """The intake answers. Every field optional, in both directions.

    Bounds mirror the CHECK constraints in schema.py rather than trusting them: a 422 at
    the boundary names the offending field, a constraint violation is a 500 that does not.
    They are typo rails and nothing more.
    """

    # Stripped first, so "  " is a 422 rather than a blank name on the profile.
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)
    ] | None = None
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    height_cm: int | None = Field(default=None, ge=50, le=280)
    bodyweight_kg: Decimal | None = Field(default=None, ge=20, le=500, decimal_places=2)
    goal: Goal | None = None
    experience: Experience | None = None
    days_per_week: int | None = Field(default=None, ge=1, le=7)
    session_minutes: int | None = Field(default=None, ge=10, le=300)


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


# scrypt from the standard library rather than a bcrypt/argon2 dependency: memory-hard,
# salted, and already installed. n=2**14 is the stdlib's documented interactive setting.
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def password_matches(password: str, stored: str) -> bool:
    _, salt, digest = stored.split("$")
    got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **SCRYPT)
    return hmac.compare_digest(got.hex(), digest)


# Checked against when the address is unknown, so a miss costs the same scrypt as a
# wrong password and response time does not say which one it was.
_DECOY = hash_password(secrets.token_hex(16))


def issue_session(user_id: uuid.UUID) -> Session:
    now = datetime.now(UTC)
    expires = now + SESSION_TTL
    claims = {"sub": str(user_id), "iat": int(now.timestamp()), "exp": int(expires.timestamp())}
    return Session(access_token=jwt.encode(claims, jwt_secret(), ALGORITHM), expires_at=expires)


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
    # Onboarding is the page that reads ?token= and signs in; /auth/verify is the API
    # call it makes, not a page, and a link pointing there opened a 404.
    send_link(email, f"{BASE_URL}/onboarding?token={token}")
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
    return issue_session(row.user_id)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(body: Credentials, db: Annotated[sa.Engine, Depends(engine)]) -> Session:
    """Create an account with a password (D31).

    An address that already has an account is refused, password or not: setting a
    password on someone else's magic-link account would be taking it over.
    """
    email = body.email.strip()
    user_id = uuid.uuid4()
    with db.begin() as conn:
        taken = conn.execute(
            sa.select(users.c.id).where(sa.func.lower(users.c.email) == email.lower())
        ).scalar_one_or_none()
        if taken is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "an account with that email already exists"
            )
        conn.execute(
            sa.insert(users).values(
                id=user_id, email=email, password_hash=hash_password(body.password)
            )
        )
    return issue_session(user_id)


@router.post("/login")
def login(body: Credentials, db: Annotated[sa.Engine, Depends(engine)]) -> Session:
    """Unknown address, magic-link-only account and wrong password all answer the same."""
    with db.connect() as conn:
        row = conn.execute(
            sa.select(users.c.id, users.c.password_hash).where(
                sa.func.lower(users.c.email) == body.email.strip().lower()
            )
        ).one_or_none()
    stored = row.password_hash if row is not None and row.password_hash else _DECOY
    if not password_matches(body.password, stored) or row is None or not row.password_hash:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong email or password")
    return issue_session(row.id)


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
    return Me(id=row.id, email=row.email, created_at=row.created_at)


PROFILE_FIELDS = tuple(Profile.model_fields)


def _profile(row: sa.Row[tuple[object, ...]]) -> Profile:
    return Profile(**{f: getattr(row, f) for f in PROFILE_FIELDS})


@router.get("/profile")
def read_profile(user_id: CurrentUser, db: Annotated[sa.Engine, Depends(engine)]) -> Profile:
    with db.connect() as conn:
        row = conn.execute(sa.select(users).where(users.c.id == user_id)).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no such user")
    return _profile(row)


@router.put("/profile")
def write_profile(
    body: Profile, user_id: CurrentUser, db: Annotated[sa.Engine, Depends(engine)]
) -> Profile:
    """Merge, not replace.

    Intake saves one screen at a time and settings edits one field at a time, so an
    omitted key means "leave it alone" and an explicit null means "clear it". Full
    replacement would make the second intake screen wipe the first.

    Nothing here is logged. This is health-adjacent data and the only reason it is stored
    at all is that a consumer is expected later (D29).
    """
    values = body.model_dump(exclude_unset=True)
    with db.begin() as conn:
        if conn.execute(sa.select(users.c.id).where(users.c.id == user_id)).one_or_none() is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no such user")
        if values:
            conn.execute(sa.update(users).where(users.c.id == user_id).values(**values))
        return _profile(
            conn.execute(sa.select(users).where(users.c.id == user_id)).one()
        )
