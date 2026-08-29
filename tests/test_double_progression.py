"""1.2: the §8 state machine, D13's two bounds through every path, D15's exemption."""

import uuid
from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from engine.progression import (
    MAX_INCREASE_RATIO,
    Decision,
    ExerciseState,
    LoggedSet,
    next_prescription,
)

D = Decimal
EX = uuid.UUID(int=1)
HARDER = uuid.UUID(int=2)
EASIER = uuid.UUID(int=3)

# A fixed-dumbbell rack: 2.5kg steps, so 25% at the bottom and 14% higher up.
RACK = [D(x) for x in ("2.5", "5", "7.5", "10", "12.5", "15", "17.5", "20", "22.5", "25")]
# A barbell with small plates: every step is well inside the ceiling.
BAR = [D(20) + D("2.5") * i for i in range(40)]


DEFAULT_LOAD = D("60")


def state(
    load: Decimal | None = DEFAULT_LOAD, reps: int = 8, **kw: object
) -> ExerciseState:
    return ExerciseState(
        exercise_id=EX, rep_range=(8, 12), current_load=load, current_reps=reps, **kw  # type: ignore[arg-type]
    )


def walk(_: uuid.UUID, direction: int) -> uuid.UUID | None:
    return HARDER if direction > 0 else EASIER


def dead_end(_: uuid.UUID, __: int) -> uuid.UUID | None:
    return None


# --- the state machine, path by path -----------------------------------------


def test_inside_the_range_adds_a_rep_and_holds_load() -> None:
    got = next_prescription(state(), [LoggedSet(9, 2, D("60"))], BAR)
    assert got.decision is Decision.ADD_REPS
    assert got.target_reps == 10
    assert got.load == D("60")


def test_top_of_range_with_reserve_increases_load_and_resets_reps() -> None:
    got = next_prescription(state(), [LoggedSet(12, 1, D("60"))], BAR)
    assert got.decision is Decision.INCREASE_LOAD
    assert got.load == D("62.5")
    assert got.target_reps == 8


def test_top_of_range_at_failure_holds_the_load() -> None:
    """RIR 0 means it was not earned yet; repeat rather than load a set at failure."""
    got = next_prescription(state(), [LoggedSet(12, 0, D("60"))], BAR)
    assert got.decision is Decision.HOLD_AT_TOP
    assert got.load == D("60")


def test_one_miss_counts_a_failure_without_deloading() -> None:
    got = next_prescription(state(), [LoggedSet(5, 0, D("60"))], BAR)
    assert got.decision is Decision.COUNT_FAILURE
    assert got.load == D("60")
    assert got.next_state.consecutive_failures == 1


def test_two_consecutive_failures_deload_by_at_least_ten_percent() -> None:
    got = next_prescription(
        state(consecutive_failures=1), [LoggedSet(5, 0, D("60"))], BAR
    )
    assert got.decision is Decision.DELOAD
    assert got.load is not None and got.load <= D("60") * D("0.90")
    assert got.next_state.consecutive_failures == 0


def test_a_cleared_session_clears_the_failure_count() -> None:
    """Two failures must be consecutive, so a good session in between resets it."""
    got = next_prescription(
        state(consecutive_failures=1), [LoggedSet(9, 2, D("60"))], BAR
    )
    assert got.next_state.consecutive_failures == 0


def test_the_limiting_set_decides_not_the_best_one() -> None:
    """Otherwise one good set out of four advances the load."""
    sets = [LoggedSet(12, 3, D("60")), LoggedSet(12, 3, D("60")), LoggedSet(8, 0, D("60"))]
    got = next_prescription(state(), sets, BAR)
    assert got.decision is Decision.ADD_REPS


def test_nothing_logged_repeats_the_prescription() -> None:
    got = next_prescription(state(), [], BAR)
    assert got.decision is Decision.REPEAT
    assert got.load == D("60")


# --- D13 ---------------------------------------------------------------------


def test_an_increment_over_the_ceiling_holds_and_adds_reps() -> None:
    """10kg -> 12.5kg is 25%, so the rack stalls here by design."""
    got = next_prescription(state(load=D("10"), reps=12), [LoggedSet(12, 2, D("10"))], RACK)
    assert got.decision is Decision.HOLD_INCREMENT_TOO_LARGE
    assert got.load == D("10")
    assert got.target_reps == 13, "reps go past the top of the range instead"


def test_the_same_increment_higher_up_the_rack_progresses() -> None:
    got = next_prescription(
        state(load=D("20"), reps=12), [LoggedSet(12, 2, D("20"))], RACK
    )
    assert got.decision is Decision.INCREASE_LOAD
    assert got.load == D("22.5")


# --- D15 ---------------------------------------------------------------------


def test_a_seeded_state_is_corrected_past_the_normal_bounds() -> None:
    """A seed 60% low must not take four sessions to converge."""
    got = next_prescription(
        state(load=D("25"), is_estimated=True), [LoggedSet(10, 1, D("60"))], BAR
    )
    assert got.decision is Decision.CORRECT_ESTIMATE
    assert got.load is not None
    assert (got.load - D("25")) / D("25") > MAX_INCREASE_RATIO
    assert not got.next_state.is_estimated, "the flag clears after one session"


def test_the_correction_happens_only_once() -> None:
    first = next_prescription(
        state(load=D("25"), is_estimated=True), [LoggedSet(10, 1, D("60"))], BAR
    )
    second = next_prescription(first.next_state, [LoggedSet(12, 1, first.load)], BAR)
    assert second.decision is Decision.INCREASE_LOAD
    assert first.load is not None and second.load is not None
    assert (second.load - first.load) / first.load <= MAX_INCREASE_RATIO


def test_a_seed_that_was_too_high_is_corrected_downward() -> None:
    got = next_prescription(
        state(load=D("100"), is_estimated=True), [LoggedSet(6, 0, D("40"))], BAR
    )
    assert got.decision is Decision.CORRECT_ESTIMATE
    assert got.load is not None and got.load < D("100")


# --- the non-loadable branch -------------------------------------------------


def test_a_bodyweight_movement_progresses_by_walking_an_edge() -> None:
    got = next_prescription(state(load=None), [LoggedSet(12, 2)], [], walk)
    assert got.decision is Decision.STEP_UP_DIFFICULTY
    assert got.exercise_id == HARDER
    assert got.load is None
    assert got.target_reps == 8


def test_the_node_reached_across_an_edge_is_seeded_not_measured() -> None:
    """D15 again: arriving somewhere new means the state there is a guess."""
    got = next_prescription(state(load=None), [LoggedSet(12, 2)], [], walk)
    assert got.next_state.is_estimated


def test_two_failures_on_bodyweight_step_down_instead_of_deloading() -> None:
    got = next_prescription(
        state(load=None, consecutive_failures=1), [LoggedSet(4, 0)], [], walk
    )
    assert got.decision is Decision.STEP_DOWN_DIFFICULTY
    assert got.exercise_id == EASIER


def test_the_end_of_the_chain_keeps_adding_reps_rather_than_stalling() -> None:
    got = next_prescription(state(load=None, reps=12), [LoggedSet(12, 2)], [], dead_end)
    assert got.decision is Decision.HOLD_INCREMENT_TOO_LARGE
    assert got.target_reps == 13


def test_an_inverted_rep_range_raises() -> None:
    bad = ExerciseState(EX, (12, 8), D("60"), 10)
    with pytest.raises(ValueError, match="inverted"):
        next_prescription(bad, [LoggedSet(10, 1, D("60"))], BAR)


# --- properties --------------------------------------------------------------

loads = st.sampled_from([RACK, BAR])
SETTINGS = settings(max_examples=400, deadline=None)


@SETTINGS
@given(
    rack=loads,
    idx=st.integers(min_value=0, max_value=30),
    reps=st.integers(min_value=1, max_value=20),
    rir=st.integers(min_value=0, max_value=4),
    failures=st.integers(min_value=0, max_value=1),
    bottom=st.integers(min_value=3, max_value=10),
    span=st.integers(min_value=0, max_value=6),
)
def test_load_never_rises_past_either_d13_bound(
    rack: list[Decimal], idx: int, reps: int, rir: int, failures: int, bottom: int, span: int
) -> None:
    """Both bounds, every path, deload included. is_estimated is excluded by design."""
    assume(idx < len(rack))
    current = rack[idx]
    st_ = ExerciseState(EX, (bottom, bottom + span), current, reps, failures, False)
    got = next_prescription(st_, [LoggedSet(reps, rir, current)], rack, walk)
    if got.load is None or got.exercise_id != EX:
        return
    if got.load <= current:
        return
    # Bound one: exactly one increment, which is what "max(10%, one increment)" allows.
    above = [x for x in rack if x > current]
    assert got.load == above[0]
    # Bound two: the hard ceiling, not implied by bound one.
    assert (got.load - current) / current <= MAX_INCREASE_RATIO


@SETTINGS
@given(
    rack=loads,
    idx=st.integers(min_value=0, max_value=30),
    reps=st.integers(min_value=1, max_value=20),
    rir=st.integers(min_value=0, max_value=4),
)
def test_a_deload_never_raises_the_load(
    rack: list[Decimal], idx: int, reps: int, rir: int
) -> None:
    assume(idx < len(rack))
    current = rack[idx]
    st_ = ExerciseState(EX, (8, 12), current, reps, 1, False)
    got = next_prescription(st_, [LoggedSet(reps, rir, current)], rack)
    if got.decision is Decision.DELOAD:
        assert got.load is not None and got.load <= current


@SETTINGS
@given(
    rack=loads,
    idx=st.integers(min_value=0, max_value=30),
    reps=st.integers(min_value=1, max_value=20),
    rir=st.integers(min_value=0, max_value=4),
    estimated=st.booleans(),
)
def test_the_estimated_flag_always_clears_after_a_logged_session(
    rack: list[Decimal], idx: int, reps: int, rir: int, estimated: bool
) -> None:
    """D15 allows the exemption exactly once, so the flag may never survive."""
    assume(idx < len(rack))
    current = rack[idx]
    st_ = ExerciseState(EX, (8, 12), current, reps, 0, estimated)
    got = next_prescription(st_, [LoggedSet(reps, rir, current)], rack, walk)
    if got.exercise_id == EX:
        assert not got.next_state.is_estimated


@SETTINGS
@given(
    rack=loads,
    idx=st.integers(min_value=0, max_value=30),
    reps=st.integers(min_value=1, max_value=20),
    rir=st.integers(min_value=0, max_value=4),
    failures=st.integers(min_value=0, max_value=1),
)
def test_a_deload_never_fires_before_two_consecutive_failures(
    rack: list[Decimal], idx: int, reps: int, rir: int, failures: int
) -> None:
    assume(idx < len(rack))
    st_ = ExerciseState(EX, (8, 12), rack[idx], reps, failures, False)
    got = next_prescription(st_, [LoggedSet(reps, rir, rack[idx])], rack)
    if got.decision is Decision.DELOAD:
        assert failures == 1 and reps < 8


def test_a_correcting_set_too_far_from_failure_anchors_on_the_load_lifted() -> None:
    """12 reps at RIR 4 is 16 to failure, past where D5's table means anything.

    Found by the property test below. The set is a legitimate log, so raising would
    crash a real prescription; the load was moved, so it is still a usable anchor.
    """
    got = next_prescription(
        state(load=D("25"), is_estimated=True), [LoggedSet(12, 4, D("60"))], BAR
    )
    assert got.decision is Decision.CORRECT_ESTIMATE
    assert got.load == D("60")
    assert not got.next_state.is_estimated
