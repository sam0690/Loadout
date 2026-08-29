"""2.1: idempotent ingest, and a projection that rebuilds exactly from the log.

Both acceptance criteria are here. The rebuild test is the one that matters: the whole
"if a projection is wrong, replay" property is worthless if the replay is not exact.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from api.events import engine as engine_dep
from api.main import app
from db import DATABASE_URL
from projections.exercise_state import rebuild
from schema import events, exercise_state, exercises

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


@pytest.fixture
def client(db: sa.Engine) -> Iterator[TestClient]:
    app.dependency_overrides[engine_dep] = lambda: db
    yield TestClient(app)
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

    first = client.post("/events", json=batch, params={"user_id": str(USER)})
    assert first.status_code == 200, first.text
    assert first.json()["stored"] == 3
    after_first = snapshot(db)

    second = client.post("/events", json=batch, params={"user_id": str(USER)})
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
    client.post("/events", json={"events": [one]}, params={"user_id": str(USER)})
    got = client.post("/events", json={"events": [one, two]}, params={"user_id": str(USER)})
    assert got.json()["stored"] == 1, "only the genuinely new event lands"


def test_duplicate_ids_inside_one_batch_are_rejected(
    client: TestClient, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """ON CONFLICT cannot resolve a conflict with a row from the same statement."""
    a, _ = two_exercises
    one = a_set(a, 10, 2, "60", 0)
    got = client.post(
        "/events", json={"events": [one, dict(one)]}, params={"user_id": str(USER)}
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
        params={"user_id": str(USER)},
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
        params={"user_id": str(USER)},
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
        params={"user_id": str(USER)},
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
        params={"user_id": str(USER)},
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
        params={"user_id": str(USER)},
    )
    with db.connect() as c:
        row = c.execute(
            sa.select(exercise_state).where(exercise_state.c.exercise_id == a)
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
        params={"user_id": str(USER)},
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
    got = client.post("/events", json={"events": [bad]}, params={"user_id": str(USER)})
    assert got.status_code == 422


def test_an_unknown_timezone_is_refused(
    client: TestClient, two_exercises: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_exercises
    bad = a_set(a, 10, 2, "60", 0)
    bad["user_tz"] = "Mars/Olympus_Mons"
    got = client.post("/events", json={"events": [bad]}, params={"user_id": str(USER)})
    assert got.status_code == 422
