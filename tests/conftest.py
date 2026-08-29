"""Point the whole suite at a throwaway database.

test_migrations runs `alembic downgrade base`, which drops every table. Against the
development database that silently destroys the seeded catalog, so tests get their own.
POSTGRES_DB is set before `db` is imported anywhere; db's .env parse uses setdefault, so
the real environment wins over the file.
"""

import os
import subprocess

TEST_DB = "loadout_test"
os.environ.pop("DATABASE_URL", None)
os.environ["POSTGRES_DB"] = TEST_DB

import sqlalchemy as sa  # noqa: E402

from db import DATABASE_URL  # noqa: E402


def _create_test_database() -> None:
    admin = sa.create_engine(
        DATABASE_URL.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as c:
        exists = c.execute(
            sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB}
        ).scalar()
        if not exists:
            c.execute(sa.text(f'CREATE DATABASE "{TEST_DB}"'))
    admin.dispose()


def seed_catalog() -> None:
    """Load equipment, exercises and edges into the test database.

    Callable rather than inline, because more than one thing needs it: the session start,
    and anything that empties the database on purpose. Equipment is a prerequisite for
    exercises (the loader resolves every slug through the alias table), exercises for
    edges, and edges for anything that traverses the graph.
    """
    from ingest.edges import SEED as EDGE_SEED
    from ingest.edges import load_edges
    from ingest.equipment import load as load_equipment
    from ingest.equipment import read_seed
    from ingest.load import full_catalog
    from ingest.load import load as load_exercises

    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        load_equipment(conn, read_seed())
        load_exercises(conn, full_catalog())
        load_edges(conn, EDGE_SEED)
    engine.dispose()


def pytest_sessionstart() -> None:
    _create_test_database()
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"], check=True, capture_output=True
    )
    seed_catalog()
