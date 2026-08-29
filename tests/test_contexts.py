"""2.2b: contexts CRUD, ownership, and the D21 load overrides through HTTP."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import insert as pg_insert

from api.auth import ALGORITHM
from api.auth import engine as auth_engine
from api.contexts import engine as contexts_engine
from api.main import app
from db import DATABASE_URL, jwt_secret
from schema import training_contexts, users

ME = uuid.UUID(int=101)
SOMEONE_ELSE = uuid.UUID(int=102)


@pytest.fixture(scope="module")
def db() -> sa.Engine:
    return sa.create_engine(DATABASE_URL)


def session_for(user_id: uuid.UUID) -> dict[str, str]:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=1)).timestamp()),
    }
    return {"Authorization": f"Bearer {jwt.encode(claims, jwt_secret(), ALGORITHM)}"}


@pytest.fixture(autouse=True)
def accounts(db: sa.Engine) -> None:
    with db.begin() as c:
        for uid in (ME, SOMEONE_ELSE):
            c.execute(
                pg_insert(users)
                .values(id=uid, email=f"ctx-{uid}@example.test")
                .on_conflict_do_nothing(index_elements=["id"])
            )
        c.execute(
            sa.delete(training_contexts).where(
                training_contexts.c.user_id.in_([ME, SOMEONE_ELSE])
            )
        )


@pytest.fixture
def client(db: sa.Engine) -> Iterator[TestClient]:
    app.dependency_overrides[contexts_engine] = lambda: db
    app.dependency_overrides[auth_engine] = lambda: db
    yield TestClient(app, headers=session_for(ME))
    app.dependency_overrides.clear()


@pytest.fixture
def other(db: sa.Engine, client: TestClient) -> TestClient:
    return TestClient(app, headers=session_for(SOMEONE_ELSE))


def body(**kw: Any) -> dict[str, Any]:
    return {"label": "home", "equipment_added": ["dumbbells", "pull_up_bar"], **kw}


# --- create and read ----------------------------------------------------------


def test_creating_a_context_resolves_its_equipment(client: TestClient) -> None:
    got = client.post("/contexts", json=body())
    assert got.status_code == 201, got.text
    slugs = {e["slug"] for e in got.json()["equipment"]}
    assert slugs == {"dumbbells", "pull_up_bar"}


def test_equipment_can_be_named_by_brand_alias(client: TestClient) -> None:
    """The API and the ingest share one resolver, so they cannot drift on what a name means."""
    got = client.post("/contexts", json=body(equipment_added=["Bowflex SelectTech"]))
    assert got.status_code == 201
    assert [e["slug"] for e in got.json()["equipment"]] == ["dumbbells"]


def test_unknown_equipment_is_refused_rather_than_invented(client: TestClient) -> None:
    got = client.post("/contexts", json=body(equipment_added=["ThighMaster 3000"]))
    assert got.status_code == 422
    assert "ThighMaster" in got.text


def test_an_unknown_archetype_is_refused(client: TestClient) -> None:
    assert client.post("/contexts", json=body(archetype_slug="nope")).status_code == 422


# --- D21 load overrides -------------------------------------------------------


def test_a_context_can_declare_its_own_rack(client: TestClient) -> None:
    got = client.post(
        "/contexts",
        json=body(loads={"dumbbells": {"load_increments": ["5", "10", "15", "20"]}}),
    )
    assert got.status_code == 201, got.text
    dumbbells = next(e for e in got.json()["equipment"] if e["slug"] == "dumbbells")
    assert [float(x) for x in dumbbells["load_increments"]] == [5, 10, 15, 20]


def test_equipment_without_an_override_keeps_the_catalog_default(client: TestClient) -> None:
    got = client.post("/contexts", json=body(equipment_added=["kettlebell"]))
    kb = next(e for e in got.json()["equipment"] if e["slug"] == "kettlebell")
    assert kb["load_increments"], "the catalog default stands (D21)"


def test_a_bar_weight_can_be_declared(client: TestClient) -> None:
    got = client.post(
        "/contexts",
        json=body(equipment_added=["barbell", "plates"], loads={"barbell": {"bar_weight": "15"}}),
    )
    assert got.status_code == 201, got.text
    bar = next(e for e in got.json()["equipment"] if e["slug"] == "barbell")
    assert float(bar["bar_weight"]) == 15.0


def test_an_override_that_says_nothing_is_refused(client: TestClient) -> None:
    got = client.post("/contexts", json=body(loads={"dumbbells": {}}))
    assert got.status_code == 422
    assert "catalog default" in got.text


def test_unsorted_increments_are_refused(client: TestClient) -> None:
    got = client.post(
        "/contexts", json=body(loads={"dumbbells": {"load_increments": ["10", "5"]}})
    )
    assert got.status_code == 422
    assert "sorted" in got.text


# --- ownership ----------------------------------------------------------------


def test_someone_elses_context_is_not_found_rather_than_forbidden(
    client: TestClient, other: TestClient
) -> None:
    """403 confirms the id exists. 404 says nothing."""
    mine = client.post("/contexts", json=body()).json()["id"]
    assert other.get(f"/contexts/{mine}").status_code == 404
    assert other.put(f"/contexts/{mine}", json=body(label="stolen")).status_code == 404
    assert other.delete(f"/contexts/{mine}").status_code == 404


def test_listing_only_returns_your_own(client: TestClient, other: TestClient) -> None:
    client.post("/contexts", json=body(label="mine"))
    other.post("/contexts", json=body(label="theirs"))
    labels = [c["label"] for c in client.get("/contexts").json()]
    assert labels == ["mine"]


def test_contexts_require_a_session() -> None:
    assert TestClient(app).get("/contexts").status_code == 401


# --- the default --------------------------------------------------------------


def test_the_first_context_is_the_default_whatever_was_asked(client: TestClient) -> None:
    """A user with contexts but no default has no session to start."""
    got = client.post("/contexts", json=body(is_default=False))
    assert got.json()["is_default"] is True


def test_only_one_context_is_ever_the_default(client: TestClient, db: sa.Engine) -> None:
    first = client.post("/contexts", json=body(label="home")).json()
    second = client.post("/contexts", json=body(label="gym", is_default=True)).json()
    assert second["is_default"] is True
    assert client.get(f"/contexts/{first['id']}").json()["is_default"] is False
    with db.connect() as c:
        defaults = c.execute(
            sa.select(sa.func.count())
            .select_from(training_contexts)
            .where(training_contexts.c.user_id == ME, training_contexts.c.is_default.is_(True))
        ).scalar_one()
    assert defaults == 1


def test_two_users_can_each_have_a_default(client: TestClient, other: TestClient) -> None:
    """The uniqueness is per user, not global."""
    assert client.post("/contexts", json=body()).json()["is_default"] is True
    assert other.post("/contexts", json=body()).json()["is_default"] is True


def test_deleting_the_default_promotes_another(client: TestClient) -> None:
    """Never leave a user holding contexts with no default."""
    first = client.post("/contexts", json=body(label="a")).json()
    client.post("/contexts", json=body(label="b"))
    assert client.delete(f"/contexts/{first['id']}").status_code == 204
    remaining = client.get("/contexts").json()
    assert len(remaining) == 1
    assert remaining[0]["is_default"] is True


def test_deleting_the_last_context_leaves_nothing_behind(client: TestClient) -> None:
    only = client.post("/contexts", json=body()).json()
    assert client.delete(f"/contexts/{only['id']}").status_code == 204
    assert client.get("/contexts").json() == []


# --- replace ------------------------------------------------------------------


def test_replacing_a_context_replaces_its_loads_too(client: TestClient) -> None:
    made = client.post(
        "/contexts", json=body(loads={"dumbbells": {"load_increments": ["5", "10"]}})
    ).json()
    updated = client.put(
        f"/contexts/{made['id']}",
        json=body(label="renamed", equipment_added=["dumbbells"]),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["label"] == "renamed"
    dumbbells = next(e for e in updated.json()["equipment"] if e["slug"] == "dumbbells")
    assert len(dumbbells["load_increments"]) > 2, "the override was dropped, catalog stands"
