"""Hashing and session-token arithmetic. No HTTP and no database.

The **link** is stateful, because single-use is the property that matters and a
self-contained token cannot express it. The **session** is a stateless JWT (D23), which
buys no per-request database hit at the cost of no revocation.
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta

import jwt

from db import jwt_secret

ALGORITHM = "HS256"
LINK_TTL = timedelta(minutes=15)
# No revocation exists (D23), so the window a leaked token stays usable is exactly this.
SESSION_TTL = timedelta(days=7)


def hash_token(token: str) -> str:
    """Only the hash is stored, so a leaked database hands out no logins."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_link_token() -> str:
    return secrets.token_urlsafe(32)


# scrypt from the standard library rather than a bcrypt/argon2 dependency: memory-hard,
# salted, and already installed. n=2**14 is the stdlib's documented interactive setting.
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def password_matches(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **SCRYPT)
    except ValueError:
        # A stored value that is not ours (corrupt, or some future format) matches
        # nothing, so login answers 401 rather than 500. The link still signs them in.
        return False
    return hmac.compare_digest(got.hex(), digest)


# Checked against when the address is unknown, so a miss costs the same scrypt as a
# wrong password and response time does not say which one it was.
DECOY = hash_password(secrets.token_hex(16))


def encode_session(user_id: uuid.UUID, now: datetime) -> tuple[str, datetime]:
    expires = now + SESSION_TTL
    claims = {"sub": str(user_id), "iat": int(now.timestamp()), "exp": int(expires.timestamp())}
    return jwt.encode(claims, jwt_secret(), ALGORITHM), expires


def decode_session(token: str) -> uuid.UUID:
    """Raises jwt.InvalidTokenError or ValueError for anything that is not a live session."""
    claims = jwt.decode(
        token,
        jwt_secret(),
        algorithms=[ALGORITHM],
        # A token without an expiry never expires, so its absence is a rejection
        # rather than a default.
        options={"require": ["sub", "exp", "iat"]},
    )
    return uuid.UUID(claims["sub"])
