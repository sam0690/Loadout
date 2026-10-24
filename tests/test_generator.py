"""1.4: 1000 generated plans, asserting every invariant in CLAUDE.md's testing section.

The build prompt calls this the test that matters most in the project.
"""

import uuid
from datetime import date, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from engine.generator import Candidate, Experience, Goal, Plan, generate_plan, target_sets
from engine.progression.volume import Landmark

MONDAY = date(2026, 8, 31)
PATTERNS = ["horizontal_press", "vertical_pull", "squat", "hinge", "elbow_flexion"]
MUSCLE_BY_PATTERN = {
    "horizontal_press": "chest",
    "vertical_pull": "lats",
    "squat": "quads",
    "hinge": "hamstrings",
    "elbow_flexion": "biceps",
}
EQUIPMENT = ["barbell", "plates", "dumbbells", "kettlebell", "flat_bench", "pull_up_bar"]
LANDMARKS = {
    "chest": Landmark(8, 14, 22),
    "lats": Landmark(10, 16, 25),
    "quads": Landmark(8, 16, 20),
    "hamstrings": Landmark(6, 12, 20),
    "biceps": Landmark(8, 14, 26),
}


@st.composite
def catalogs(draw: st.DrawFn) -> list[Candidate]:
    n = draw(st.integers(min_value=1, max_value=18))
    out = []
    for i in range(n):
        pattern = draw(st.sampled_from(PATTERNS))
        out.append(
            Candidate(
                exercise_id=uuid.UUID(int=i + 1),
                slug=f"ex_{i:02d}",
                movement_pattern=pattern,
                primary_muscle=MUSCLE_BY_PATTERN[pattern],
                equipment=frozenset(
                    draw(st.lists(st.sampled_from(EQUIPMENT), max_size=3, unique=True))
                ),
                difficulty=draw(st.integers(min_value=1, max_value=10)),
                loadable=draw(st.booleans()),
            )
        )
    return out


day_sets = st.lists(
    st.integers(min_value=0, max_value=6), min_size=1, max_size=5, unique=True
).map(lambda offsets: sorted(MONDAY + timedelta(days=o) for o in offsets))

PLANS = settings(
    max_examples=1000, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)

COMMON = {
    "days": day_sets,
    "catalog": catalogs(),
    "available_equipment": st.frozensets(st.sampled_from(EQUIPMENT), max_size=6),
    "budget": st.integers(min_value=0, max_value=120),
    "experience": st.sampled_from(list(Experience)),
    "goal": st.sampled_from(list(Goal)),
}


def build(
    days: list[date],
    catalog: list[Candidate],
    available_equipment: frozenset[str],
    budget: int,
    experience: Experience,
    goal: Goal,
) -> Plan:
    return generate_plan(
        days=days, catalog=catalog, available_equipment=available_equipment,
        landmarks=LANDMARKS, time_budget_minutes=budget, experience=experience, goal=goal,
    )


@PLANS
@given(**COMMON)
def test_every_prescribed_exercise_fits_the_context_equipment(
    days: list[date], catalog: list[Candidate], available_equipment: frozenset[str],
    budget: int, experience: Experience, goal: Goal,
) -> None:
    """CLAUDE.md invariant 4."""
    by_id = {c.exercise_id: c for c in catalog}
    plan = build(days, catalog, available_equipment, budget, experience, goal)
    for session in plan.sessions:
        for item in session.items:
            assert by_id[item.exercise_id].equipment <= available_equipment


@PLANS
@given(**COMMON)
def test_weekly_hard_sets_never_exceed_mrv(
    days: list[date], catalog: list[Candidate], available_equipment: frozenset[str],
    budget: int, experience: Experience, goal: Goal,
) -> None:
    """CLAUDE.md invariant 2, against D7's prescription-side definition of hard."""
    plan = build(days, catalog, available_equipment, budget, experience, goal)
    for muscle, count in plan.weekly_hard_sets().items():
        assert count <= LANDMARKS[muscle].mrv, f"{muscle}: {count}"


@PLANS
@given(**COMMON)
def test_no_muscle_is_programmed_hard_on_consecutive_days(
    days: list[date], catalog: list[Candidate], available_equipment: frozenset[str],
    budget: int, experience: Experience, goal: Goal,
) -> None:
    """CLAUDE.md invariant 3, calendar days in the user's zone per D14."""
    plan = build(days, catalog, available_equipment, budget, experience, goal)
    by_day = {
        s.day: {i.primary_muscle for i in s.items} for s in plan.sessions
    }
    for day, muscles in by_day.items():
        clash = muscles & by_day.get(day + timedelta(days=1), set())
        assert not clash, f"{clash} on {day} and the day after"


@PLANS
@given(**COMMON)
def test_every_prescribed_set_is_hard_and_within_the_time_budget(
    days: list[date], catalog: list[Candidate], available_equipment: frozenset[str],
    budget: int, experience: Experience, goal: Goal,
) -> None:
    from engine.generator.plan import MINUTES_PER_SET

    plan = build(days, catalog, available_equipment, budget, experience, goal)
    for session in plan.sessions:
        assert session.hard_sets * MINUTES_PER_SET <= budget
        for item in session.items:
            assert item.target_rir <= 3, "D7: everything prescribed here is a hard set"
            assert item.sets >= 1
            assert item.target_reps >= 1


@PLANS
@given(**COMMON)
def test_generation_is_deterministic(
    days: list[date], catalog: list[Candidate], available_equipment: frozenset[str],
    budget: int, experience: Experience, goal: Goal,
) -> None:
    """Replay diffs engine versions, so the same input must give the same plan (D6)."""
    a = build(days, catalog, available_equipment, budget, experience, goal)
    b = build(days, catalog, available_equipment, budget, experience, goal)
    assert a == b


@PLANS
@given(**COMMON)
def test_no_exercise_appears_twice_in_one_session(
    days: list[date], catalog: list[Candidate], available_equipment: frozenset[str],
    budget: int, experience: Experience, goal: Goal,
) -> None:
    plan = build(days, catalog, available_equipment, budget, experience, goal)
    for session in plan.sessions:
        ids = [i.exercise_id for i in session.items]
        assert len(ids) == len(set(ids))


@PLANS
@given(**COMMON)
def test_a_plan_never_exceeds_the_weekly_target(
    days: list[date], catalog: list[Candidate], available_equipment: frozenset[str],
    budget: int, experience: Experience, goal: Goal,
) -> None:
    plan = build(days, catalog, available_equipment, budget, experience, goal)
    for muscle, count in plan.weekly_hard_sets().items():
        assert count <= target_sets(LANDMARKS[muscle], experience)


# --- worked behaviour --------------------------------------------------------


def full_catalog() -> list[Candidate]:
    return [
        Candidate(uuid.UUID(int=i + 1), f"ex_{p}", p, MUSCLE_BY_PATTERN[p],
                  frozenset(), 3, True)
        for i, p in enumerate(PATTERNS)
    ]


def test_a_zero_time_budget_produces_nothing() -> None:
    plan = build([MONDAY], full_catalog(), frozenset(), 0, Experience.BEGINNER, Goal.STRENGTH)
    assert plan.sessions == ()


def test_an_empty_catalog_produces_nothing() -> None:
    plan = build([MONDAY], [], frozenset(), 90, Experience.BEGINNER, Goal.STRENGTH)
    assert plan.sessions == ()


def test_equipment_the_user_lacks_is_never_prescribed() -> None:
    catalog = [
        Candidate(uuid.UUID(int=1), "barbell_squat", "squat", "quads",
                  frozenset({"barbell", "plates"}), 5, True),
        Candidate(uuid.UUID(int=2), "bodyweight_squat", "squat", "quads",
                  frozenset(), 3, False),
    ]
    plan = build([MONDAY], catalog, frozenset(), 90, Experience.BEGINNER, Goal.STRENGTH)
    slugs = [i.slug for s in plan.sessions for i in s.items]
    assert slugs == ["bodyweight_squat"]


def test_a_loadable_exercise_is_preferred_when_the_context_can_load_it() -> None:
    """Equipment fit: the option that can progress by load scores higher."""
    catalog = [
        Candidate(uuid.UUID(int=1), "a_bodyweight", "squat", "quads", frozenset(), 3, False),
        Candidate(uuid.UUID(int=2), "b_loadable", "squat", "quads",
                  frozenset({"dumbbells"}), 3, True),
    ]
    plan = build([MONDAY], catalog, frozenset({"dumbbells"}), 30,
                 Experience.BEGINNER, Goal.STRENGTH)
    assert plan.sessions[0].items[0].slug == "b_loadable"


def test_substitutes_are_shipped_with_the_plan() -> None:
    """PRD §6: resolved at generation, because the swap happens with no signal."""
    from engine.generator import Substitute

    subs = (Substitute(uuid.UUID(int=99), "alt_exercise", ("dumbbells",)),)
    plan = generate_plan(
        days=[MONDAY], catalog=full_catalog(), available_equipment=frozenset(),
        landmarks=LANDMARKS, time_budget_minutes=60,
        substitutes_for=lambda _: subs,
    )
    assert all(i.substitutes == subs for s in plan.sessions for i in s.items)


def test_goal_sets_the_rep_target() -> None:
    strength = build([MONDAY], full_catalog(), frozenset(), 60, Experience.BEGINNER, Goal.STRENGTH)
    hypertrophy = build(
        [MONDAY], full_catalog(), frozenset(), 60, Experience.BEGINNER, Goal.HYPERTROPHY
    )
    assert strength.sessions[0].items[0].target_reps == 5
    assert hypertrophy.sessions[0].items[0].target_reps == 10


def test_experience_raises_the_weekly_target() -> None:
    chest = LANDMARKS["chest"]
    assert target_sets(chest, Experience.BEGINNER) == chest.mev
    assert target_sets(chest, Experience.ADVANCED) == chest.mav
    assert chest.mev < target_sets(chest, Experience.INTERMEDIATE) < chest.mav


def test_consecutive_days_force_a_muscle_to_alternate() -> None:
    days = [MONDAY + timedelta(days=i) for i in range(3)]
    plan = build(days, full_catalog()[:1], frozenset(), 90, Experience.ADVANCED, Goal.STRENGTH)
    trained = sorted(s.day for s in plan.sessions)
    for a, b in zip(trained, trained[1:], strict=False):
        assert (b - a).days >= 2


# --- coverage: what the equipment cannot express (D30) ------------------------


@PLANS
@given(**COMMON)
def test_unreachable_is_exactly_the_muscles_with_no_usable_exercise(
    days: list[date], catalog: list[Candidate], available_equipment: frozenset[str],
    budget: int, experience: Experience, goal: Goal,
) -> None:
    """Not "was not programmed" -- "cannot be programmed with this equipment".

    Asserted as an equality rather than a subset in both directions separately, because
    the two failures are different bugs: a muscle missing from `unreachable` is the
    silent hole this field exists to close, and a muscle wrongly in it would tell a user
    to buy equipment they do not need.
    """
    plan = build(days, catalog, available_equipment, budget, experience, goal)
    expected = {
        m for m in LANDMARKS
        if not any(
            c.primary_muscle == m and c.equipment <= available_equipment for c in catalog
        )
    }
    assert set(plan.unreachable) == expected


@PLANS
@given(**COMMON)
def test_an_unreachable_muscle_is_never_prescribed(
    days: list[date], catalog: list[Candidate], available_equipment: frozenset[str],
    budget: int, experience: Experience, goal: Goal,
) -> None:
    plan = build(days, catalog, available_equipment, budget, experience, goal)
    prescribed = {i.primary_muscle for s in plan.sessions for i in s.items}
    assert prescribed.isdisjoint(plan.unreachable)


def test_an_empty_rack_cannot_reach_anything_needing_equipment() -> None:
    """The case that prompted this: a user with nothing, and an honest answer."""
    catalog = [
        Candidate(exercise_id=uuid.uuid4(), slug="floor_press", movement_pattern="horizontal_press",
                  primary_muscle="chest", equipment=frozenset(), difficulty=3, loadable=False),
        Candidate(exercise_id=uuid.uuid4(), slug="pull_up", movement_pattern="vertical_pull",
                  primary_muscle="lats", equipment=frozenset({"pull_up_bar"}), difficulty=3,
                  loadable=False),
    ]
    plan = generate_plan(
        days=[date(2026, 8, 31)], catalog=catalog, available_equipment=frozenset(),
        landmarks={"chest": LANDMARKS["chest"], "lats": LANDMARKS["lats"]},
        time_budget_minutes=60,
    )
    assert plan.unreachable == ("lats",)
    assert {i.slug for s in plan.sessions for i in s.items} == {"floor_press"}


def test_a_full_rack_reaches_everything() -> None:
    catalog = [
        Candidate(exercise_id=uuid.uuid4(), slug="row", movement_pattern="horizontal_pull",
                  primary_muscle="lats", equipment=frozenset({"sturdy_table"}), difficulty=3,
                  loadable=False),
    ]
    plan = generate_plan(
        days=[date(2026, 8, 31)], catalog=catalog,
        available_equipment=frozenset({"sturdy_table"}),
        landmarks={"lats": LANDMARKS["lats"]}, time_budget_minutes=60,
    )
    assert plan.unreachable == ()
