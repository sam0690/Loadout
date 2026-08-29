"""Connection URL, shared by alembic, the loaders and the tests.

Host 5432 is taken by a native postgres on the dev machine; compose maps 5433.
"""

import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://loadout:loadout@localhost:5433/loadout"
)
