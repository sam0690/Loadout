"""Run the whole pipeline: fetch (cached) -> normalize -> load.

    uv run python -m ingest

Each stage also runs on its own; see the module docstrings.
"""

import sqlalchemy as sa

from db import DATABASE_URL
from ingest import edges, equipment, fetch, load, normalize


def main() -> None:
    fetch.main()
    equipment.main()
    normalize.main()
    load.main()
    # Loads the reviewed file; never regenerates it. `uv run python -m ingest.edges
    # --force` is a deliberate, separate act because it discards hand corrections.
    if edges.SEED.exists():
        engine = sa.create_engine(DATABASE_URL)
        with engine.begin() as conn:
            print(f"loaded {edges.load_edges(conn)} edges from {edges.SEED.name}")


if __name__ == "__main__":
    main()
