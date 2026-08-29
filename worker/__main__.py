"""Run the plan worker.

    docker compose up -d
    uv run python -m worker
"""

from redis import Redis
from rq import Queue, SimpleWorker

from db import redis_url


def main() -> None:
    connection = Redis.from_url(redis_url())
    # SimpleWorker: no fork, so a traceback in a job lands in this process's log rather
    # than a child's. One queue, and the job is arithmetic over a database.
    SimpleWorker([Queue("plans", connection=connection)], connection=connection).work()


if __name__ == "__main__":
    main()
