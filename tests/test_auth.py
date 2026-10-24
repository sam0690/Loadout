"""2.2a: the magic-link cycle, every rejection path, and the hole this closes.

Until this task POST /events took user_id as a query parameter with nothing behind it, so
anyone could write events attributed to anyone. The last test in this file is the one that
matters most.
"""

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from api.auth import ALGORITHM, hash_token
from api.auth import engine as auth_engine
from api.events import engine as events_engine
from api.main import app
from db import DATABASE_URL, jwt_secret
from schema import events, exercise_state, exercises, magic_links, users

EMAIL = "sam@example.com"
OTHER = "someone.else@example.com"


@pytest.fixture(scope="module")
def db() -> sa.Engine:
    return sa.create_engine(DATABASE_URL)


@pytest.fixture
def client(db: sa.Engine) -> Iterator[TestClient]:
    app.dependency_overrides[auth_engine] = lambda: db
    app.dependency_overrides[events_engine] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clean(db: sa.Engine) -> None:
    with db.begin() as c:
        ids = c.execute(
            sa.select(users.c.id).where(
                sa.func.lower(users.c.email).in_([EMAIL, OTHER])
            )
        ).scalars().all()
        if ids:
            c.execute(sa.text("ALTER TABLE events DISABLE TRIGGER events_no_update_or_delete"))
            c.execute(sa.delete(events).where(events.c.user_id.in_(ids)))
            c.execute(sa.text("ALTER TABLE events ENABLE TRIGGER events_no_update_or_delete"))
            c.execute(sa.delete(exercise_state).where(exercise_state.c.user_id.in_(ids)))
            c.execute(sa.delete(users).where(users.c.id.in_(ids)))


def link_token(caplog: pytest.LogCaptureFixture) -> str:
    """Pull the token out of the logged link, the way a user pulls it out of an email."""
    found = re.search(r"token=([\w\-]+)", caplog.text)
    assert found, f"no magic link logged: {caplog.text!r}"
    return str(found.group(1))


def login(client: TestClient, caplog: pytest.LogCaptureFixture, email: str = EMAIL) -> str:
    caplog.clear()
    with caplog.at_level("INFO", logger="loadout.auth"):
        assert client.post("/auth/request", json={"email": email}).status_code == 202
    got = client.post("/auth/verify", json={"token": link_token(caplog)})
    assert got.status_code == 200, got.text
    token: str = got.json()["access_token"]
    return token


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- the happy path ----------------------------------------------------------


def test_the_full_magic_link_cycle(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    token = login(client, caplog)
    me = client.get("/auth/me", headers=auth(token))
    assert me.status_code == 200
    assert me.json()["email"] == EMAIL


def test_the_token_is_never_stored_in_the_clear(
    client: TestClient, db: sa.Engine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.clear()
    with caplog.at_level("INFO", logger="loadout.auth"):
        client.post("/auth/request", json={"email": EMAIL})
    raw = link_token(caplog)
    with db.connect() as c:
        stored = c.execute(sa.select(magic_links.c.token_hash)).scalars().all()
    assert raw not in stored, "a leaked database must not hand out logins"
    assert hash_token(raw) in stored


def test_an_address_that_logs_in_twice_is_still_one_account(
    client: TestClient, db: sa.Engine, caplog: pytest.LogCaptureFixture
) -> None:
    login(client, caplog, EMAIL)
    login(client, caplog, EMAIL.upper())
    with db.connect() as c:
        count = c.execute(
            sa.select(sa.func.count())
            .select_from(users)
            .where(sa.func.lower(users.c.email) == EMAIL)
        ).scalar_one()
    assert count == 1, "addresses are case-insensitive in practice"


# --- rejection paths ---------------------------------------------------------


def test_a_link_works_only_once(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.clear()
    with caplog.at_level("INFO", logger="loadout.auth"):
        client.post("/auth/request", json={"email": EMAIL})
    token = link_token(caplog)
    assert client.post("/auth/verify", json={"token": token}).status_code == 200
    second = client.post("/auth/verify", json={"token": token})
    assert second.status_code == 401, "a link forwarded or logged elsewhere is spent"


def test_an_expired_link_is_refused(
    client: TestClient, db: sa.Engine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.clear()
    with caplog.at_level("INFO", logger="loadout.auth"):
        client.post("/auth/request", json={"email": EMAIL})
    token = link_token(caplog)
    with db.begin() as c:
        c.execute(
            sa.update(magic_links)
            .where(magic_links.c.token_hash == hash_token(token))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert client.post("/auth/verify", json={"token": token}).status_code == 401


def test_an_unknown_link_is_refused(client: TestClient) -> None:
    assert client.post("/auth/verify", json={"token": "not-a-real-token"}).status_code == 401


def test_requesting_a_link_never_reveals_whether_the_address_is_known(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """An unauthenticated endpoint that answers differently is an enumeration oracle."""
    login(client, caplog, EMAIL)  # now a known address
    with caplog.at_level("INFO", logger="loadout.auth"):
        known = client.post("/auth/request", json={"email": EMAIL})
        unknown = client.post("/auth/request", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()


@pytest.mark.parametrize(
    "header",
    [None, {"Authorization": "Bearer garbage"}, {"Authorization": "Basic abc"}],
    ids=["absent", "malformed", "wrong-scheme"],
)
def test_a_bad_session_token_is_refused(
    client: TestClient, header: dict[str, str] | None
) -> None:
    assert client.get("/auth/me", headers=header or {}).status_code == 401


def test_an_expired_session_token_is_refused(client: TestClient) -> None:
    now = datetime.now(UTC)
    stale = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": int((now - timedelta(days=30)).timestamp()),
            "exp": int((now - timedelta(days=1)).timestamp()),
        },
        jwt_secret(),
        ALGORITHM,
    )
    assert client.get("/auth/me", headers=auth(stale)).status_code == 401


def test_a_token_without_an_expiry_is_refused(client: TestClient) -> None:
    """A token that never expires is worse than one that expired."""
    forever = jwt.encode({"sub": str(uuid.uuid4())}, jwt_secret(), ALGORITHM)
    assert client.get("/auth/me", headers=auth(forever)).status_code == 401


def test_a_token_signed_with_the_wrong_key_is_refused(client: TestClient) -> None:
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=1)).timestamp()),
        },
        "not-the-real-secret",
        ALGORITHM,
    )
    assert client.get("/auth/me", headers=auth(forged)).status_code == 401


# --- the hole this task closes ------------------------------------------------


def test_events_now_require_a_session(client: TestClient) -> None:
    got = client.post("/events", json={"events": []})
    assert got.status_code in (401, 422), "no anonymous writes"


def test_a_session_cannot_write_events_as_another_user(
    client: TestClient, db: sa.Engine, caplog: pytest.LogCaptureFixture
) -> None:
    """The regression test for 2.1's query-parameter user_id.

    Attacker holds a valid session and names the victim in every place the old API took a
    user id. Every event must still land under the attacker's own id.
    """
    with db.connect() as c:
        exercise_id = c.execute(
            sa.select(exercises.c.id).order_by(exercises.c.slug).limit(1)
        ).scalar_one()

    victim_token = login(client, caplog, OTHER)
    victim = uuid.UUID(
        client.get("/auth/me", headers=auth(victim_token)).json()["id"]
    )
    attacker_token = login(client, caplog, EMAIL)
    attacker = uuid.UUID(
        client.get("/auth/me", headers=auth(attacker_token)).json()["id"]
    )
    assert attacker != victim

    payload: dict[str, Any] = {
        "events": [
            {
                "id": str(uuid.uuid4()),
                "type": "set_logged",
                "payload": {
                    "exercise_id": str(exercise_id), "reps": 10, "rir": 2, "load": "60",
                    "target_bottom": 8, "target_top": 12,
                },
                "client_ts": datetime.now(UTC).isoformat(),
                "user_tz": "Europe/London",
            }
        ]
    }
    got = client.post(
        "/events",
        json=payload,
        params={"user_id": str(victim)},  # ignored: the old attack surface
        headers=auth(attacker_token),
    )
    assert got.status_code == 200, got.text

    with db.connect() as c:
        owners = c.execute(
            sa.select(events.c.user_id).where(events.c.user_id.in_([attacker, victim]))
        ).scalars().all()
    assert owners == [attacker], "the token decides the owner, not the request"


def test_unread_links_are_rate_limited_without_changing_the_response(
    client: TestClient, db: sa.Engine, caplog: pytest.LogCaptureFixture
) -> None:
    """The limit must not become the enumeration oracle the endpoint avoids."""
    from api.auth import MAX_OUTSTANDING_LINKS

    bodies, statuses = [], []
    with caplog.at_level("INFO", logger="loadout.auth"):
        for _ in range(MAX_OUTSTANDING_LINKS + 2):
            got = client.post("/auth/request", json={"email": EMAIL})
            statuses.append(got.status_code)
            bodies.append(got.json())
    assert set(statuses) == {202}, "throttling is invisible from outside"
    assert len(set(map(str, bodies))) == 1

    with db.connect() as c:
        issued = c.execute(
            sa.select(sa.func.count())
            .select_from(magic_links)
            .join(users, users.c.id == magic_links.c.user_id)
            .where(sa.func.lower(users.c.email) == EMAIL)
        ).scalar_one()
    assert issued == MAX_OUTSTANDING_LINKS, "no more links than the cap were created"


def test_consuming_a_link_frees_the_allowance(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Logging in repeatedly is fine; accumulating unread links is what is capped."""
    from api.auth import MAX_OUTSTANDING_LINKS

    for _ in range(MAX_OUTSTANDING_LINKS + 3):
        token = login(client, caplog, EMAIL)
        assert client.get("/auth/me", headers=auth(token)).status_code == 200


def test_the_magic_link_actually_reaches_a_log_handler() -> None:
    """The link is the only delivery mechanism (D23), so it must actually be emitted.

    It was not: `loadout.auth` logs at INFO and Python's root default is WARNING, so
    every link was silently dropped and nobody could ever sign in.
    """
    import logging

    import api.main  # noqa: F401  -- importing configures logging

    assert logging.getLogger("loadout.auth").isEnabledFor(logging.INFO)


# --- the profile (D29) -------------------------------------------------------


def test_profile_starts_empty_and_survives_a_round_trip(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    token = login(client, caplog)
    assert client.get("/auth/profile", headers=auth(token)).json() == {
        "birth_year": None, "height_cm": None, "bodyweight_kg": None,
        "goal": None, "experience": None, "days_per_week": None,
        "session_minutes": None,
    }

    written = client.put(
        "/auth/profile",
        headers=auth(token),
        json={"birth_year": 1990, "height_cm": 178, "bodyweight_kg": "82.50",
              "goal": "strength", "experience": "advanced",
              "days_per_week": 4, "session_minutes": 45},
    )
    assert written.status_code == 200, written.text
    assert client.get("/auth/profile", headers=auth(token)).json() == written.json()
    assert written.json()["goal"] == "strength"


def test_a_partial_write_leaves_the_other_answers_alone(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Intake saves one screen at a time, so screen two must not wipe screen one."""
    token = login(client, caplog)
    client.put("/auth/profile", headers=auth(token), json={"birth_year": 1990})
    client.put("/auth/profile", headers=auth(token), json={"goal": "hypertrophy"})

    got = client.get("/auth/profile", headers=auth(token)).json()
    assert got["birth_year"] == 1990
    assert got["goal"] == "hypertrophy"


def test_an_explicit_null_clears_an_answer(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    token = login(client, caplog)
    client.put("/auth/profile", headers=auth(token), json={"height_cm": 178})
    client.put("/auth/profile", headers=auth(token), json={"height_cm": None})
    assert client.get("/auth/profile", headers=auth(token)).json()["height_cm"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"height_cm": 1900},          # cm/mm confusion, the reason the rail exists
        {"birth_year": 1800},
        {"bodyweight_kg": 0},
        {"days_per_week": 8},
        {"session_minutes": 5},
        {"goal": "aesthetics"},       # not in the engine's Goal enum
        {"experience": "elite"},
    ],
)
def test_out_of_range_answers_are_refused_at_the_boundary(
    client: TestClient, caplog: pytest.LogCaptureFixture, body: dict[str, Any]
) -> None:
    token = login(client, caplog)
    assert client.put("/auth/profile", headers=auth(token), json=body).status_code == 422


def test_the_profile_needs_a_session(client: TestClient) -> None:
    assert client.get("/auth/profile").status_code == 401
    assert client.put("/auth/profile", json={"birth_year": 1990}).status_code == 401


def test_profile_values_are_never_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Health-adjacent data. The magic-link path already logs; this one must not."""
    token = login(client, caplog)
    caplog.clear()
    with caplog.at_level("DEBUG"):
        client.put("/auth/profile", headers=auth(token), json={"bodyweight_kg": "82.50"})
    assert "82.5" not in caplog.text
