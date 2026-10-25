"""Shared FastAPI dependencies. The HTTP edge: everything here may speak status codes."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

import jwt
import sqlalchemy as sa
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis import Redis
from rq import Queue

from api.core.config import get_settings
from api.core.security import decode_session

_engine = sa.create_engine(get_settings().database_url)
_queue = Queue("plans", connection=Redis.from_url(get_settings().redis_url))
_bearer = HTTPBearer(auto_error=False)


def get_engine() -> sa.Engine:
    return _engine


def get_queue() -> Queue:
    return _queue


def utcnow() -> datetime:
    return datetime.now(UTC)


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
        return decode_session(creds.credentials)
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc


Db = Annotated[sa.Engine, Depends(get_engine)]
RQ = Annotated[Queue, Depends(get_queue)]
Now = Annotated[datetime, Depends(utcnow)]
CurrentUser = Annotated[uuid.UUID, Depends(current_user)]
