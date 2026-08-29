"""Database URL, assembled from the environment.

No credentials in source. Set them in .env, which is gitignored — copy .env.example.
Docker Compose reads that file natively; this parses it for everything else rather
than pulling in python-dotenv for six lines.
"""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent / ".env"


def _load_env_file(path: Path = ENV_FILE) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Real environment wins, so CI and one-off overrides do not need the file.
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def build_url() -> str:
    _load_env_file()
    if url := os.environ.get("DATABASE_URL"):
        return url
    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError(
            "No database credentials. Copy .env.example to .env, or set DATABASE_URL."
        )
    user = os.environ.get("POSTGRES_USER", "loadout")
    name = os.environ.get("POSTGRES_DB", "loadout")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    # Host 5432 is often taken by a native postgres; compose maps 5433.
    port = os.environ.get("POSTGRES_PORT", "5433")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


DATABASE_URL = build_url()


def redis_url() -> str:
    """Queue backend. Unlike the database and the signing key this has a default: it
    holds no data worth protecting and losing it costs a re-queued job, nothing more."""
    _load_env_file()
    if url := os.environ.get("REDIS_URL"):
        return url
    return f"redis://localhost:{os.environ.get('REDIS_PORT', '6380')}/0"


def jwt_secret() -> str:
    """Signing key for session tokens. Required, with no default.

    A default here would mean every deployment that forgot to set one shares a secret,
    and anybody who read the source could mint a session for any user.
    """
    _load_env_file()
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError(
            "JWT_SECRET is not set. Copy .env.example to .env and put a random value in "
            "it: python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    return secret
