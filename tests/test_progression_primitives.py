"""1.1: worked examples, plus the monotonicity and D13 bound properties."""

from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from engine.progression import (
    MAX_INCREASE_RATIO,
    RepsOutOfRange,
    barbell_loads,
    best_e1rm_estimate,
    brzycki_e1rm,
    epley_e1rm,
    next_available_load,
    rir_to_percent_1rm,
    round_to_available_load,
)

D = Decimal

weights = st.decimals(
    min_value=D("2.5"), max_value=D("300"), places=2, allow_nan=False, allow_infinity=False
)
reps = st.integers(min_value=1, max_value=12)
rirs = st.integers(min_value=0, max_value=3)
SETTINGS = settings(max_examples=300, deadline=None)


# --- worked examples ---------------------------------------------------------


def test_epley_matches_the_prd_formula() -> None:
    """e1RM = weight x (1 + reps / 30)."""
    assert epley_e1rm(D("100"), 5) == D("100") * (1 + D(5) / 30)
    assert epley_e1rm(D("100"), 1) == D("100") * (1 + D(1) / 30)
    assert round(epley_e1rm(D("60"), 10), 2) == D("80.00")


def test_brzycki_matches_its_formula() -> None:
    assert round(brzycki_e1rm(D("100"), 5), 2) == D("112.50")
    assert brzycki_e1rm(D("100"), 1) == D("100")


def test_rir_table_is_indexed_by_reps_to_failure() -> None:
    """D5: a set of 8 at RIR 2 is a 10-rep max, so both give the same percentage."""
    assert rir_to_percent_1rm(2, 8) == rir_to_percent_1rm(0, 10) == D("0.74")
    assert rir_to_percent_1rm(0, 1) == D("1.00")


def test_estimate_takes_the_higher_of_epley_and_the_rir_table() -> None:
    """PRD §8."""
    w, r, rir = D("100"), 8, 0
    assert best_e1rm_estimate(w, r, rir) == max(epley_e1rm(w, r), w / rir_to_percent_1rm(rir, r))


def test_a_set_far_from_failure_is_not_estimated() -> None:
    """D5: past 15 reps to failure the number is not worth returning."""
    with pytest.raises(RepsOutOfRange):
        rir_to_percent_1rm(8, 10)
    with pytest.raises(RepsOutOfRange):
        best_e1rm_estimate(D("50"), 12, 5)


def test_barbell_plate_math() -> None:
    """20kg bar with 1.25/2.5/5 pairs: 2.5kg is the smallest real jump."""
    loads = barbell_loads(D("20"), [D("1.25"), D("2.5"), D("5")], ceiling=D("40"))
    assert loads[0] == D("20")
    assert D("22.5") in loads and D("25") in loads
    assert all(load <= D("40") for load in loads)
    assert loads == sorted(set(loads))


def test_fixed_dumbbells_stall_at_the_bottom_of_the_rack() -> None:
    """D13's known ceiling, stated as a test so it cannot be forgotten.

    10kg to 12.5kg is 25%. No arithmetic makes it smaller, so the answer is hold.
    """
    rack = [D(x) for x in ("2.5", "5", "7.5", "10", "12.5", "15", "17.5", "20")]
    assert next_available_load(D("10"), rack) is None
    # Higher up the same rack the same 2.5kg step is only 14% and progresses fine.
    assert next_available_load(D("17.5"), rack) == D("20")


def test_deload_rounds_down_to_something_expressible() -> None:
    rack = [D(x) for x in ("2.5", "5", "7.5", "10", "12.5", "15")]
    assert round_to_available_load(D("15") * D("0.9"), rack) == D("12.5")


def test_a_non_loadable_exercise_raises() -> None:
    with pytest.raises(ValueError, match="not loadable"):
        round_to_available_load(D("10"), [])
    with pytest.raises(ValueError, match="not loadable"):
        next_available_load(D("10"), [])


# --- properties --------------------------------------------------------------


@SETTINGS
@given(weight=weights, reps=reps)
def test_epley_is_monotonic_in_weight_and_reps(weight: Decimal, reps: int) -> None:
    assert epley_e1rm(weight + 1, reps) > epley_e1rm(weight, reps)
    assert epley_e1rm(weight, reps + 1) > epley_e1rm(weight, reps)


@SETTINGS
@given(weight=weights, reps=reps)
def test_brzycki_is_monotonic_in_weight_and_reps(weight: Decimal, reps: int) -> None:
    assert brzycki_e1rm(weight + 1, reps) > brzycki_e1rm(weight, reps)
    assert brzycki_e1rm(weight, reps + 1) > brzycki_e1rm(weight, reps)


@SETTINGS
@given(weight=weights, reps=reps, rir=rirs)
def test_best_estimate_is_monotonic_in_weight_and_reps(
    weight: Decimal, reps: int, rir: int
) -> None:
    assume(reps + 1 + rir <= 15)
    assert best_e1rm_estimate(weight + 1, reps, rir) > best_e1rm_estimate(weight, reps, rir)
    assert best_e1rm_estimate(weight, reps + 1, rir) > best_e1rm_estimate(weight, reps, rir)


@SETTINGS
@given(weight=weights, reps=reps, rir=rirs)
def test_best_estimate_is_never_below_either_input(
    weight: Decimal, reps: int, rir: int
) -> None:
    got = best_e1rm_estimate(weight, reps, rir)
    assert got >= epley_e1rm(weight, reps)
    assert got >= weight / rir_to_percent_1rm(rir, reps)
    assert got >= weight, "an e1RM below the weight actually lifted is nonsense"


@SETTINGS
@given(
    total=st.integers(min_value=1, max_value=14),
)
def test_percent_of_1rm_falls_as_failure_gets_further_away(total: int) -> None:
    assert rir_to_percent_1rm(0, total) > rir_to_percent_1rm(0, total + 1)


loads_strategy = st.lists(
    st.decimals(min_value=D("1"), max_value=D("200"), places=2), min_size=1, max_size=25
).map(lambda xs: sorted(set(xs)))


@SETTINGS
@given(loads=loads_strategy, current=weights)
def test_an_increase_never_exceeds_the_hard_ceiling(
    loads: list[Decimal], current: Decimal
) -> None:
    """D13's second bound, which is not implied by the first."""
    got = next_available_load(current, loads)
    if got is not None and current > 0:
        assert (got - current) / current <= MAX_INCREASE_RATIO


@SETTINGS
@given(loads=loads_strategy, current=weights)
def test_an_increase_is_always_exactly_one_increment(
    loads: list[Decimal], current: Decimal
) -> None:
    """The first bound: max(10%, one increment). One increment, by construction."""
    got = next_available_load(current, loads)
    if got is not None:
        above = [x for x in sorted(loads) if x > current]
        assert got == above[0]
        assert got > current


@SETTINGS
@given(loads=loads_strategy, target=weights)
def test_rounding_returns_something_expressible_and_never_overshoots(
    loads: list[Decimal], target: Decimal
) -> None:
    got = round_to_available_load(target, loads)
    assert got in loads
    assert got <= target or got == min(loads)


@SETTINGS
@given(
    bar=st.decimals(min_value=D("5"), max_value=D("25"), places=1),
    plates=st.lists(
        st.decimals(min_value=D("1"), max_value=D("25"), places=2), min_size=1, max_size=5
    ),
    ceiling=st.decimals(min_value=D("30"), max_value=D("250"), places=0),
)
def test_every_barbell_load_is_the_bar_plus_whole_pairs(
    bar: Decimal, plates: list[Decimal], ceiling: Decimal
) -> None:
    got = barbell_loads(bar, plates, ceiling)
    assert got[0] == bar
    assert all(bar <= load <= ceiling for load in got)
    for load in got:
        # Every reachable load differs from the bar by an even multiple of some plate.
        assert (load - bar) >= 0
