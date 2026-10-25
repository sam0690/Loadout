"""What the API reads from the environment, and the only place in api/ that reads it.

`db.py` stays the loader for the whole repo (migrations, ingest, the worker and the test
suite all import it), so this builds on it rather than parsing `.env` a second time.
JWT_SECRET is deliberately absent: it is read at use through `db.jwt_secret()`, so the
app still imports without one and only token handling fails loudly.
"""

import os
from dataclasses import dataclass
from functools import lru_cache

from db import DATABASE_URL, redis_url


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    cors_origins: list[str]
    # Where magic links point. Defaults to the dev server the Makefile starts.
    web_url: str


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=DATABASE_URL,
        redis_url=redis_url(),
        cors_origins=[
            origin.strip()
            for origin in os.environ.get(
                "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
            ).split(",")
            if origin.strip()
        ],
        web_url=os.environ.get(
            "WEB_URL", f"http://localhost:{os.environ.get('WEB_PORT', '3000')}"
        ).rstrip("/"),
    )
