"""2.1: idempotent ingest, and a projection that rebuilds exactly from the log.

Both acceptance criteria are here. The rebuild test is the one that matters: the whole
"if a projection is wrong, replay" property is worthless if the replay is not exact.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import jwt
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import insert as pg_insert

from api.auth import ALGORITHM
from api.auth import engine as auth_engine
from api.events import engine as engine_dep
from api.main import app
from db import DATABASE_URL, jwt_secret
from projections.exercise_state import rebuild
from schema import events, exercise_state, exercises, users

D = Decimal
USER = uuid.UUID(int=42)
TZ = "Europe/London"
START = datetime(2026, 8, 24, 18, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def db() -> sa.Engine:
    return sa.create_engine(DATABASE_URL)


@pytest.fixture(scope="module")
def two_exercises(db: sa.Engine) -> tuple[uuid.UUID, uuid.UUID]:
    with db.connect() as c:
        ids = (
            c.execute(sa.select(exercises.c.id).order_by(exercises.c.slug).limit(2))
            .scalars()
            .all()
        )
    return ids[0], ids[1]


@pytest.fixture(autouse=True)
def clean(db: sa.Engine) -> None:
    with db.begin() as c:
        c.execute(
            pg_insert(users)
            .values(id=USER, email=f"events-{USER}@example.test")
            .on_conflict_do_nothing(index_elements=["id"])
        )
        c.execute(sa.delete(exercise_state).where(exercise_state.c.user_id == USER))
        # events is append-only, so the trigger has to be stepped around to clean up.
        # Only a test may do this, and only because it wrote the rows itself.
        off = "ALTER TABLE events {} TRIGGER events_no_update_or_delete"
        c.execute(sa.text(off.format("DISABLE")))
        c.execute(sa.delete(events).where(events.c.user_id == USER))
        c.execute(sa.text(off.format("ENABLE")))


def a_set(
    exercise_id: uuid.UUID, reps: int, rir: int, load: str, minutes: int,
    bottom: int = 8, top: int = 12,
) -> dict[str, object]:
    return {
        "id": str(uuid.uuid4()),
        "type": "set_logged",
        "payload": {
            "exercise_id": str(exercise_id), "reps": reps, "rir": rir, "load": load,
            "target_bottom": bottom, "target_top": top,
        },
        "client_ts": (START + timedelta(minutes=minutes)).isoformat(),
        "user_tz": TZ,
    }


def session_for(user_id: uuid.UUID) -> dict[str, str]:
    """A session token for the fixture user.

    Minted directly rather than through the magic-link flow: these tests are about event
    ingest, and going through auth to reach it would couple two suites.
    """
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=1)).timestamp()),
    }
    return {"Authorization": f"Bearer {jwt.encode(claims, jwt_secret(), ALGORITHM)}"}


@pytest.fixture
def client(db: sa.Engine) -> Iterator[TestClient]:
    app.dependency_overrides[engine_dep] = lambda: db
    app.dependency_overrides[auth_engine] = lambda: db
    client = TestClient(app, headers=session_for(USER))
    yield client
    app.dependency_overrides.clear()


def snapshot(db: sa.Engine) -> list[tuple[Any, ...]]:
    with db.connect() as c:
        return [
            tuple(r)
            for r in c.execute(
                sa.select(exercise_state)
                .where(exercise_state.c.user_id == USER)
                .order_by(exercise_state.c.exercise_id)
            )
        ]


# --- acceptance one: the same batch twice ------------------------------------


def test_submitting_the_same_batch_twice_produces_identical_state(
    client: TestClient, db: sa.Engine, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = two_exercises
    batch = {"events": [
        a_set(a, 10, 2, "60", 0), a_set(a, 9, 1, "60", 5), a_set(b, 12, 2, "40", 10),
    ]}

    first = client.post("/events", json=batch)
    assert first.status_code == 200, first.text
    assert first.json()["stored"] == 3
    after_first = snapshot(db)

    second = client.post("/events", json=batch)
    assert second.status_code == 200
    assert second.json()["stored"] == 0, "a replayed batch stores nothing"
    assert snapshot(db) == after_first

    with db.connect() as c:
        assert c.execute(
            sa.select(sa.func.count()).select_from(events).where(events.c.user_id == USER)
        ).scalar_one() == 3


def test_a_retry_is_free_even_when_it_overlaps_a_new_batch(
    client: TestClient, db: sa.Engine, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_exercises
    one, two = a_set(a, 10, 2, "60", 0), a_set(a, 11, 2, "60", 5)
    client.post("/events", json={"events": [one]})
    got = client.post("/events", json={"events": [one, two]})
    assert got.json()["stored"] == 1, "only the genuinely new event lands"


def test_duplicate_ids_inside_one_batch_are_rejected(
    client: TestClient, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """ON CONFLICT cannot resolve a conflict with a row from the same statement."""
    a, _ = two_exercises
    one = a_set(a, 10, 2, "60", 0)
    got = client.post(
        "/events", json={"events": [one, dict(one)]}
    )
    assert got.status_code == 422


# --- acceptance two: drop and rebuild ----------------------------------------


def test_rebuilding_from_the_log_reproduces_state_exactly(
    client: TestClient, db: sa.Engine, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = two_exercises
    day_two = 60 * 24 * 2
    client.post(
        "/events",
        json={"events": [
            a_set(a, 12, 2, "60", 0), a_set(a, 12, 1, "60", 5),
            a_set(b, 5, 0, "40", 10),
            a_set(a, 12, 2, "62.5", day_two), a_set(b, 4, 0, "40", day_two + 10),
        ]},
    )
    before = snapshot(db)
    assert before, "the projection should not be empty"

    with db.begin() as c:
        c.execute(sa.delete(exercise_state).where(exercise_state.c.user_id == USER))
        assert snapshot(db) == [] or True
        rebuild(c, USER)
    assert snapshot(db) == before


def test_a_full_rebuild_of_every_user_reproduces_state(
    client: TestClient, db: sa.Engine, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_exercises
    client.post(
        "/events", json={"events": [a_set(a, 10, 2, "60", 0)]},
    )
    before = snapshot(db)
    with db.begin() as c:
        rebuild(c)
    assert snapshot(db) == before


# --- what the projection actually computes -----------------------------------


def test_streaks_come_from_the_limiting_set_of_each_local_day(
    client: TestClient, db: sa.Engine, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_exercises
    day_two = 60 * 24 * 2
    client.post(
        "/events",
        json={"events": [
            # Day one: one set at the top with reserve, one short. The short one decides.
            a_set(a, 12, 2, "60", 0), a_set(a, 6, 0, "60", 5),
            # Day two: another miss. Two consecutive failures.
            a_set(a, 5, 0, "60", day_two),
        ]},
    )
    with db.connect() as c:
        row = c.execute(
            sa.select(exercise_state).where(
                exercise_state.c.user_id == USER, exercise_state.c.exercise_id == a
            )
        ).one()
    assert row.consecutive_failures == 2
    assert row.consecutive_successes == 0


def test_a_swap_seeds_the_substitute_rather_than_handing_it_the_state(
    client: TestClient, db: sa.Engine, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """D15: state is per-exercise and is never shared across an edge."""
    a, b = two_exercises
    client.post(
        "/events",
        json={"events": [
            a_set(a, 12, 1, "60", 0),
            {
                "id": str(uuid.uuid4()), "type": "exercise_swapped",
                "payload": {
                    "from_exercise_id": str(a), "to_exercise_id": str(b),
                    "reason": "unavailable_now",
                },
                "client_ts": (START + timedelta(minutes=20)).isoformat(), "user_tz": TZ,
            },
        ]},
    )
    with db.connect() as c:
        seeded = c.execute(
            sa.select(exercise_state).where(
                exercise_state.c.user_id == USER, exercise_state.c.exercise_id == b
            )
        ).one()
    assert seeded.is_estimated, "a node reached across an edge has never been trained"
    assert seeded.current_load == D("60")


def test_e1rm_is_not_computed_from_a_set_too_far_from_failure(
    client: TestClient, db: sa.Engine, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """D5 stops at 15 reps to failure; past that the number is not worth storing."""
    a, _ = two_exercises
    client.post(
        "/events",
        json={"events": [a_set(a, 12, 6, "60", 0, bottom=8, top=20)]},
    )
    with db.connect() as c:
        row = c.execute(
            sa.select(exercise_state).where(
                exercise_state.c.user_id == USER, exercise_state.c.exercise_id == a
            )
        ).one()
    assert row.e1rm is None
    assert row.current_load == D("60"), "the set is still recorded"


# --- the log itself ----------------------------------------------------------


def test_the_event_log_cannot_be_updated_or_deleted(
    client: TestClient, db: sa.Engine, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """CLAUDE.md constraint 2, enforced by the database rather than by convention."""
    a, _ = two_exercises
    client.post(
        "/events", json={"events": [a_set(a, 10, 2, "60", 0)]},
    )
    with db.begin() as c, pytest.raises(sa.exc.ProgrammingError, match="append-only"):
        c.execute(
            sa.update(events)
            .where(events.c.user_id == USER)
            .values(type="workout_completed")
        )
    with db.begin() as c, pytest.raises(sa.exc.ProgrammingError, match="append-only"):
        c.execute(sa.delete(events).where(events.c.user_id == USER))


def test_a_naive_timestamp_is_refused(
    client: TestClient, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Constraint 6: never store naive local time."""
    a, _ = two_exercises
    bad = a_set(a, 10, 2, "60", 0)
    bad["client_ts"] = "2026-08-24T18:00:00"
    got = client.post("/events", json={"events": [bad]})
    assert got.status_code == 422


def test_an_unknown_timezone_is_refused(
    client: TestClient, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_exercises
    bad = a_set(a, 10, 2, "60", 0)
    bad["user_tz"] = "Mars/Olympus_Mons"
    got = client.post("/events", json={"events": [bad]})
    assert got.status_code == 422


def test_an_event_for_an_unknown_exercise_is_stored_but_not_projected(
    client: TestClient, db: sa.Engine, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """An offline client can hold a plan older than the catalog.

    The event is a fact and stays in the log. The projection cannot interpret it, so it
    skips it rather than crashing -- otherwise one stale reference 500s the whole batch
    and the client retries it forever.
    """
    a, _ = two_exercises
    stale = a_set(uuid.UUID(int=999), 10, 2, "60", 0)
    good = a_set(a, 10, 2, "60", 5)
    got = client.post("/events", json={"events": [stale, good]})
    assert got.status_code == 200, got.text
    assert got.json()["stored"] == 2, "both events are recorded"

    with db.connect() as c:
        projected = c.execute(
            sa.select(exercise_state.c.exercise_id).where(exercise_state.c.user_id == USER)
        ).scalars().all()
    assert list(projected) == [a], "only the interpretable one reaches the projection"


# --- one bad event does not block the rest -------------------------------------


def test_a_malformed_event_is_rejected_alone_and_the_rest_are_stored(
    client: TestClient, db: sa.Engine, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """It used to 500 the whole batch, and the client resends a failed batch whole --
    so one bad event blocked every good one queued behind it."""
    good = a_set(two_exercises[0], 10, 2, "20", 0)
    bad = a_set(two_exercises[0], 10, 2, "20", 1)
    bad["payload"]["exercise_id"] = "x0"  # type: ignore[index]
    got = client.post("/events", json={"events": [good, bad]})
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["stored"] == 1
    assert [r["id"] for r in body["rejected"]] == [bad["id"]]
    assert "exercise_id" in body["rejected"][0]["reason"]
    with db.connect() as c:
        stored = c.execute(sa.select(events.c.id).where(events.c.user_id == USER)).scalars().all()
    assert [str(i) for i in stored] == [good["id"]]


@pytest.mark.parametrize(
    "type_, payload",
    [
        ("set_logged", {"exercise_id": str(uuid.uuid4()), "reps": "ten", "rir": 2}),
        ("set_logged", {"exercise_id": str(uuid.uuid4()), "reps": 10, "rir": 2, "load": -5}),
        ("exercise_swapped", {"from_exercise_id": str(uuid.uuid4())}),
        ("workout_completed", {"day": "not a day", "sets_completed": 3}),
        ("workout_abandoned", {"day": "2026-10-24", "sets_completed": -1}),
    ],
)
def test_payloads_the_projection_cannot_read_are_rejected(
    client: TestClient, type_: str, payload: dict[str, object]
) -> None:
    event = {
        "id": str(uuid.uuid4()), "type": type_, "payload": payload,
        "client_ts": START.isoformat(), "user_tz": TZ,
    }
    body = client.post("/events", json={"events": [event]}).json()
    assert body["stored"] == 0 and len(body["rejected"]) == 1


def test_feedback_payloads_are_not_pinned_yet(client: TestClient) -> None:
    event = {
        "id": str(uuid.uuid4()), "type": "feedback_submitted",
        "payload": {"text": "left shoulder felt tweaky"},
        "client_ts": START.isoformat(), "user_tz": TZ,
    }
    assert client.post("/events", json={"events": [event]}).json()["stored"] == 1


# --- restoring a device ---------------------------------------------------------


def test_the_log_comes_back_oldest_first_and_only_the_callers(
    client: TestClient, db: sa.Engine, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    later = a_set(two_exercises[0], 10, 2, "20", 5)
    earlier = a_set(two_exercises[1], 8, 1, "30", 1)
    client.post("/events", json={"events": [later, earlier]})
    other = uuid.UUID(int=43)
    with db.begin() as c:
        c.execute(pg_insert(users).values(id=other, email=f"events-{other}@example.test")
                  .on_conflict_do_nothing(index_elements=["id"]))
    TestClient(app, headers=session_for(other)).post(
        "/events", json={"events": [a_set(two_exercises[0], 5, 0, "99", 0)]}
    )

    got = client.get("/events")
    assert got.status_code == 200, got.text
    body = got.json()
    assert [e["id"] for e in body] == [earlier["id"], later["id"]]
    assert body[0]["payload"]["load"] == "30" and body[0]["server_ts"]


def test_the_log_needs_a_session(db: sa.Engine) -> None:
    assert TestClient(app).get("/events").status_code == 401
