"""1.3: hard-set counting, landmarks, the deload rule, and the fatigue gate.

The acceptance property is the last one: the gate can only reduce, on every dimension.
"""

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.progression import (
    AbandonedWorkout,
    Cap,
    HardSession,
    Landmark,
    SessionWork,
    Severity,
    Soreness,
    Verdict,
    apply,
    fatigue_cap,
    is_stalled,
    should_deload,
    verdict,
    weekly_hard_sets,
)
from engine.progression.volume import LoggedSet

D = Decimal
TODAY = date(2026, 8, 29)
YESTERDAY = TODAY - timedelta(days=1)
CHEST = Landmark(mev=8, mav=14, mrv=22)


def logged(muscle: str, rir: int, day: date = TODAY) -> LoggedSet:
    return LoggedSet(primary_muscle=muscle, reps=8, rir=rir, day=day)


# --- counting ----------------------------------------------------------------


def test_only_sets_within_three_of_failure_count() -> None:
    """D7's log side: hard means actually taken to RIR 0-3."""
    sets = [logged("chest", 0), logged("chest", 3), logged("chest", 4), logged("chest", 7)]
    assert weekly_hard_sets(sets) == {"chest": 2}


def test_a_compound_credits_its_primary_muscle_only() -> None:
    """No double-counting into secondaries (PRD §8)."""
    sets = [logged("chest", 1), logged("chest", 1), logged("triceps", 1)]
    assert weekly_hard_sets(sets) == {"chest": 2, "triceps": 1}


def test_nothing_logged_counts_nothing() -> None:
    assert weekly_hard_sets([]) == {}


# --- landmarks ---------------------------------------------------------------


def test_verdicts_across_the_landmarks() -> None:
    assert verdict(7, CHEST) is Verdict.ADD_A_SET
    assert verdict(8, CHEST) is Verdict.PROGRESS
    assert verdict(14, CHEST) is Verdict.PROGRESS
    assert verdict(15, CHEST) is Verdict.HOLD


# --- the deload rule ---------------------------------------------------------


def test_a_young_block_never_deloads_however_bad_it_looks() -> None:
    assert not should_deload(3, {"chest": 99}, {"chest": CHEST}, [D(100), D(100)])


def test_week_four_deloads_on_a_signal() -> None:
    assert should_deload(4, {"chest": 22}, {"chest": CHEST}), "at MRV"
    assert should_deload(4, {"chest": 10}, {"chest": CHEST}, [D(100), D(100)]), "stalled"


def test_week_four_without_a_signal_keeps_accumulating() -> None:
    assert not should_deload(4, {"chest": 10}, {"chest": CHEST}, [D(100), D(110)])


def test_week_six_is_forced_regardless() -> None:
    assert should_deload(6, {"chest": 1}, {"chest": CHEST}, [D(100), D(200)])


def test_a_climbing_e1rm_is_not_a_stall() -> None:
    assert not is_stalled([D(100), D(110)])
    assert is_stalled([D(100), D(100)])
    assert is_stalled([D(110), D(100)]), "going backwards is certainly not progress"
    assert not is_stalled([D(100)]), "one week cannot show a trend"


# --- the fatigue gate --------------------------------------------------------

WORK = SessionWork(load=D("60"), reps=10, sets=4)


def test_a_muscle_trained_hard_yesterday_is_not_programmed_hard_today() -> None:
    """D14, and CLAUDE.md's consecutive-calendar-day invariant."""
    cap = fatigue_cap(WORK, "chest", TODAY, [HardSession("chest", YESTERDAY)])
    assert apply(WORK, cap).sets == 0


def test_a_different_muscle_is_untouched() -> None:
    cap = fatigue_cap(WORK, "lats", TODAY, [HardSession("chest", YESTERDAY)])
    assert apply(WORK, cap) == WORK


def test_two_days_ago_does_not_trigger_the_gate() -> None:
    older = HardSession("chest", TODAY - timedelta(days=2))
    assert apply(WORK, fatigue_cap(WORK, "chest", TODAY, [older])) == WORK


def test_an_abandoned_workout_caps_at_what_was_completed() -> None:
    cap = fatigue_cap(
        WORK, "chest", TODAY, abandoned=AbandonedWorkout(YESTERDAY, 2, D("50"))
    )
    got = apply(WORK, cap)
    assert got.sets == 2
    assert got.load == D("50")


def test_severe_soreness_removes_the_work() -> None:
    cap = fatigue_cap(WORK, "chest", TODAY, soreness=[Soreness("chest", Severity.SEVERE, TODAY)])
    assert apply(WORK, cap).sets == 0


def test_moderate_soreness_halves_the_sets_but_leaves_one() -> None:
    cap = fatigue_cap(
        WORK, "chest", TODAY, soreness=[Soreness("chest", Severity.MODERATE, TODAY)]
    )
    assert apply(WORK, cap).sets == 2
    single = SessionWork(D("60"), 10, 1)
    cap1 = fatigue_cap(
        single, "chest", TODAY, soreness=[Soreness("chest", Severity.MODERATE, TODAY)]
    )
    assert apply(single, cap1).sets == 1


def test_caps_compose_to_the_tightest_bound() -> None:
    cap = fatigue_cap(
        WORK, "chest", TODAY,
        hard_sessions=[HardSession("chest", YESTERDAY)],
        abandoned=AbandonedWorkout(YESTERDAY, 3, D("55")),
    )
    got = apply(WORK, cap)
    assert got.sets == 0, "the tighter of 0 and 3"
    assert got.load == D("55")
    assert len(cap.reasons) == 2


def test_the_gate_explains_itself() -> None:
    """The engine decides; §9 job 2 has the LLM narrate a reason it did not invent."""
    cap = fatigue_cap(WORK, "chest", TODAY, [HardSession("chest", YESTERDAY)])
    assert cap.reasons == ("chest was trained hard yesterday",)


def test_a_quiet_history_changes_nothing() -> None:
    assert apply(WORK, fatigue_cap(WORK, "chest", TODAY)) == WORK


# --- the acceptance property -------------------------------------------------

loads = st.one_of(st.none(), st.decimals(min_value=D("1"), max_value=D("300"), places=2))
work_strategy = st.builds(
    SessionWork,
    load=loads,
    reps=st.integers(min_value=1, max_value=30),
    sets=st.integers(min_value=0, max_value=10),
)
cap_strategy = st.builds(
    Cap,
    max_load=loads,
    max_reps=st.one_of(st.none(), st.integers(min_value=0, max_value=30)),
    max_sets=st.one_of(st.none(), st.integers(min_value=0, max_value=10)),
)
SETTINGS = settings(max_examples=500, deadline=None)


@SETTINGS
@given(work=work_strategy, cap=cap_strategy)
def test_the_gate_never_increases_anything(work: SessionWork, cap: Cap) -> None:
    """1.3's acceptance: output <= input on every dimension, including an empty cap."""
    got = apply(work, cap)
    assert got.sets <= work.sets
    assert got.reps <= work.reps
    if work.load is None:
        assert got.load is None
    else:
        assert got.load is not None and got.load <= work.load


@SETTINGS
@given(work=work_strategy, a=cap_strategy, b=cap_strategy)
def test_merging_caps_can_only_tighten(work: SessionWork, a: Cap, b: Cap) -> None:
    merged = apply(work, a.merge(b))
    for single in (apply(work, a), apply(work, b)):
        assert merged.sets <= single.sets
        assert merged.reps <= single.reps
        if merged.load is not None and single.load is not None:
            assert merged.load <= single.load


@SETTINGS
@given(work=work_strategy, cap=cap_strategy)
def test_applying_a_cap_twice_changes_nothing_further(work: SessionWork, cap: Cap) -> None:
    once = apply(work, cap)
    assert apply(once, cap) == once


@SETTINGS
@given(
    work=work_strategy,
    muscle=st.sampled_from(["chest", "lats", "quads"]),
    days_ago=st.integers(min_value=0, max_value=5),
    severity=st.sampled_from(list(Severity)),
    completed=st.integers(min_value=0, max_value=10),
)
def test_a_generated_cap_still_only_reduces(
    work: SessionWork, muscle: str, days_ago: int, severity: Severity, completed: int
) -> None:
    """The property has to hold for caps the gate actually produces, not only random ones."""
    day = TODAY - timedelta(days=days_ago)
    cap = fatigue_cap(
        work, muscle, TODAY,
        hard_sessions=[HardSession(muscle, day)],
        abandoned=AbandonedWorkout(day, completed, work.load),
        soreness=[Soreness(muscle, severity, day)],
    )
    got = apply(work, cap)
    assert got.sets <= work.sets
    assert got.reps <= work.reps
