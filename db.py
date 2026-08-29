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
