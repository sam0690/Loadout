"""2.2c: the full generate -> poll -> fetch cycle, and the OpenAPI schema it exposes.

The queue runs inline (`is_async=False`) against fakeredis, so the whole cycle exercises
the real job, the real engine and the real catalog without a worker process. What that
does not cover is a worker crashing mid-job, which is a deployment concern rather than a
logic one.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import fakeredis
import jwt
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from rq import Queue
from sqlalchemy.dialects.postgresql import insert as pg_insert

from api.auth import ALGORITHM
from api.auth import engine as auth_engine
from api.contexts import engine as contexts_engine
from api.main import app
from api.plans import engine as plans_engine
from api.plans import queue as queue_dep
from db import DATABASE_URL, jwt_secret
from engine import ENGINE_VERSION
from schema import plans, training_contexts, users

ME = uuid.UUID(int=201)
INTRUDER = uuid.UUID(int=202)
# A Monday, so the ISO-week validation has something predictable to work with.
MONDAY = date(2026, 8, 31)


@pytest.fixture(scope="module")
def db() -> sa.Engine:
    return sa.create_engine(DATABASE_URL)


def session_for(user_id: uuid.UUID) -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {
                "sub": str(user_id),
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(days=1)).timestamp()),
            },
            jwt_secret(),
            ALGORITHM,
        )
    }


@pytest.fixture(autouse=True)
def accounts(db: sa.Engine) -> None:
    with db.begin() as c:
        for uid in (ME, INTRUDER):
            c.execute(
                pg_insert(users)
                .values(id=uid, email=f"plans-{uid}@example.test")
                .on_conflict_do_nothing(index_elements=["id"])
            )
        c.execute(sa.delete(plans).where(plans.c.user_id.in_([ME, INTRUDER])))
        c.execute(
            sa.delete(training_contexts).where(
                training_contexts.c.user_id.in_([ME, INTRUDER])
            )
        )


@pytest.fixture
def q() -> Queue:
    """Inline queue: enqueue runs the job immediately, so a test needs no worker."""
    return Queue("plans", connection=fakeredis.FakeStrictRedis(), is_async=False)


@pytest.fixture
def client(db: sa.Engine, q: Queue) -> Iterator[TestClient]:
    for dep in (auth_engine, contexts_engine, plans_engine):
        app.dependency_overrides[dep] = lambda: db
    app.dependency_overrides[queue_dep] = lambda: q
    yield TestClient(app, headers=session_for(ME))
    app.dependency_overrides.clear()


def make_context(client: TestClient, **kw: Any) -> uuid.UUID:
    got = client.post(
        "/contexts",
        json={
            "label": "home",
            "equipment_added": ["dumbbells", "pull_up_bar", "flat_bench"],
            **kw,
        },
    )
    assert got.status_code == 201, got.text
    return uuid.UUID(got.json()["id"])


def request_plan(client: TestClient, context_id: uuid.UUID, **kw: Any) -> dict[str, Any]:
    body = {
        "training_context_id": str(context_id),
        "days": [(MONDAY + timedelta(days=i)).isoformat() for i in (0, 2, 4)],
        "time_budget_minutes": 60,
        **kw,
    }
    got = client.post("/plans", json=body)
    assert got.status_code == 202, got.text
    result: dict[str, Any] = got.json()
    return result


# --- the acceptance cycle ------------------------------------------------------


def test_generate_poll_fetch(client: TestClient) -> None:
    """2.2's stated acceptance, end to end against the real catalog."""
    context_id = make_context(client)

    job_id = request_plan(client, context_id)["job_id"]

    polled = client.get(f"/jobs/{job_id}")
    assert polled.status_code == 200, polled.text
    assert polled.json()["status"] == "finished"
    plan_id = polled.json()["plan_id"]

    fetched = client.get("/plans/current")
    assert fetched.status_code == 200, fetched.text
    body = fetched.json()
    assert body["id"] == plan_id
    assert body["week_of"] == MONDAY.isoformat()
    assert body["engine_version"] == ENGINE_VERSION

    sessions = body["payload"]["sessions"]
    assert sessions, "the real catalog should produce real sessions"
    assert all(item["sets"] >= 1 for s in sessions for item in s["items"])


def test_the_plan_ships_its_substitutes(client: TestClient) -> None:
    """PRD §6: resolved at generation, because the swap happens with no signal."""
    context_id = make_context(client)
    request_plan(client, context_id)
    payload = client.get("/plans/current").json()["payload"]
    shipped = [
        item for s in payload["sessions"] for item in s["items"] if item["substitutes"]
    ]
    assert shipped, "the seeded graph should give at least some exercises a fallback"


def test_only_equipment_the_context_has_is_prescribed(client: TestClient) -> None:
    context_id = make_context(client, equipment_added=["dumbbells"])
    request_plan(client, context_id)
    payload = client.get("/plans/current").json()["payload"]
    slugs = {i["slug"] for s in payload["sessions"] for i in s["items"]}
    assert slugs, "a dumbbell-only context still gets a plan"


def test_regenerating_a_week_replaces_it(client: TestClient, db: sa.Engine) -> None:
    context_id = make_context(client)
    request_plan(client, context_id)
    request_plan(client, context_id, time_budget_minutes=30)
    with db.connect() as c:
        rows = c.execute(
            sa.select(sa.func.count()).select_from(plans).where(plans.c.user_id == ME)
        ).scalar_one()
    assert rows == 1, "one plan per user per week; the newest wins"


def test_loads_are_not_mangled_by_the_json_round_trip(client: TestClient) -> None:
    """Decimal survives as a string: 2.5kg steps do not survive binary floating point."""
    context_id = make_context(client)
    request_plan(client, context_id)
    payload = client.get("/plans/current").json()["payload"]
    loads = [i["load"] for s in payload["sessions"] for i in s["items"]]
    assert all(load is None or isinstance(load, str) for load in loads)


# --- validation and ownership --------------------------------------------------


def test_days_must_fall_in_one_week(client: TestClient) -> None:
    context_id = make_context(client)
    got = client.post(
        "/plans",
        json={
            "training_context_id": str(context_id),
            "days": [MONDAY.isoformat(), (MONDAY + timedelta(days=8)).isoformat()],
            "time_budget_minutes": 60,
        },
    )
    assert got.status_code == 422
    assert "same ISO week" in got.text


def test_duplicate_days_are_refused(client: TestClient) -> None:
    context_id = make_context(client)
    got = client.post(
        "/plans",
        json={
            "training_context_id": str(context_id),
            "days": [MONDAY.isoformat(), MONDAY.isoformat()],
            "time_budget_minutes": 60,
        },
    )
    assert got.status_code == 422


def test_planning_against_someone_elses_context_is_not_found(
    client: TestClient, q: Queue
) -> None:
    mine = make_context(client)
    intruder = TestClient(app, headers=session_for(INTRUDER))
    got = intruder.post(
        "/plans",
        json={
            "training_context_id": str(mine),
            "days": [MONDAY.isoformat()],
            "time_budget_minutes": 60,
        },
    )
    assert got.status_code == 404


def test_polling_someone_elses_job_is_not_found(client: TestClient) -> None:
    """A job id is guessable enough that polling must not leak another user's plan."""
    context_id = make_context(client)
    job_id = request_plan(client, context_id)["job_id"]
    intruder = TestClient(app, headers=session_for(INTRUDER))
    assert intruder.get(f"/jobs/{job_id}").status_code == 404


def test_an_unknown_job_is_not_found(client: TestClient) -> None:
    assert client.get(f"/jobs/{uuid.uuid4()}").status_code == 404


def test_no_plan_yet_is_not_found(client: TestClient) -> None:
    assert client.get("/plans/current").status_code == 404


def test_every_plan_route_requires_a_session() -> None:
    anon = TestClient(app)
    assert anon.get("/plans/current").status_code == 401
    assert anon.get(f"/jobs/{uuid.uuid4()}").status_code == 401
    assert anon.post("/plans", json={}).status_code in (401, 422)


# --- the schema the TS client is generated from --------------------------------


def test_the_openapi_schema_is_clean() -> None:
    """2.2's other acceptance: the generated TS client is only as good as this."""
    schema = app.openapi()
    operations = [
        (path, method, op)
        for path, methods in schema["paths"].items()
        for method, op in methods.items()
    ]
    ids = [op["operationId"] for _, _, op in operations]
    assert len(ids) == len(set(ids)), "duplicate operationIds collide in the client"
    for path, method, op in operations:
        assert op.get("responses"), f"{method} {path} declares no responses"
        assert "summary" in op or "operationId" in op
    # Every schema a response references must actually be defined, or the generator
    # emits `any` and the strict-mode client silently loses its types.
    defined = set(schema.get("components", {}).get("schemas", {}))
    referenced = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                referenced.add(ref.rsplit("/", 1)[1])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema["paths"])
    walk(schema.get("components", {}))
    assert referenced <= defined, f"dangling refs: {referenced - defined}"


def test_a_shipped_substitute_carries_enough_to_render_offline(client: TestClient) -> None:
    """PRD §6: the swap happens mid-set with no signal.

    A bare id would be useless there — the client cannot show "swap to X" for a uuid it
    has no name for, and looking it up is exactly the request that will not succeed.
    """
    context_id = make_context(client)
    request_plan(client, context_id)
    payload = client.get("/plans/current").json()["payload"]
    shipped = [
        s for sess in payload["sessions"] for i in sess["items"] for s in i["substitutes"]
    ]
    assert shipped, "the seeded graph should give some exercises a fallback"
    for substitute in shipped:
        assert substitute["slug"], "a name, not just an id"
        assert "equipment" in substitute, "so the user can see what it needs"
        assert isinstance(substitute["equipment"], list)
