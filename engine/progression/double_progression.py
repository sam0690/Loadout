"""Double progression state machine (PRD §8). Pure functions.

Takes state and returns a decision. No database, no clock. Graph traversal for the
non-loadable branch arrives as a callback rather than an import, so this module stays
independent of engine.graph and can be tested without building one.
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from engine.progression.primitives import (
    MAX_REPS_TO_FAILURE,
    best_e1rm_estimate,
    next_available_load,
    rir_to_percent_1rm,
    round_to_available_load,
)

DELOAD_RATIO = Decimal("0.90")
FAILURES_BEFORE_DELOAD = 2

# The RIR we aim to leave at the top of the range when re-deriving a load from scratch.
# One in reserve, matching the RIR >= 1 the progression rule requires to advance.
TARGET_RIR = 1

# Walk a difficulty_step edge: (exercise_id, +1 harder | -1 easier) -> exercise_id.
# None means the chain ends there.
WalkDifficulty = Callable[[uuid.UUID, int], uuid.UUID | None]


class Decision(StrEnum):
    """What the engine decided, for the projection and for the LLM to narrate.

    The LLM never chooses one of these — it renders the one already chosen (PRD §9).
    """

    ADD_REPS = "add_reps"
    INCREASE_LOAD = "increase_load"
    HOLD_AT_TOP = "hold_at_top"  # top of range but RIR 0: earn it before loading up
    HOLD_INCREMENT_TOO_LARGE = "hold_increment_too_large"  # D13 blocked the step
    COUNT_FAILURE = "count_failure"
    DELOAD = "deload"
    STEP_UP_DIFFICULTY = "step_up_difficulty"
    STEP_DOWN_DIFFICULTY = "step_down_difficulty"
    CORRECT_ESTIMATE = "correct_estimate"  # D15, once, past the normal bounds
    REPEAT = "repeat"  # nothing logged yet


@dataclass(frozen=True)
class ExerciseState:
    exercise_id: uuid.UUID
    rep_range: tuple[int, int]
    current_load: Decimal | None  # None for a non-loadable exercise
    current_reps: int
    consecutive_failures: int = 0
    is_estimated: bool = False


@dataclass(frozen=True)
class LoggedSet:
    reps: int
    rir: int
    load: Decimal | None = None


@dataclass(frozen=True)
class Prescription:
    exercise_id: uuid.UUID
    load: Decimal | None
    target_reps: int
    decision: Decision
    next_state: ExerciseState


def next_prescription(
    state: ExerciseState,
    last_session_sets: Sequence[LoggedSet],
    available_loads: Sequence[Decimal],
    walk_difficulty: WalkDifficulty | None = None,
) -> Prescription:
    """The next prescription for one exercise.

    `available_loads` is what the equipment can express, already composed — plate math
    lives in `barbell_loads` and belongs to the caller, since the plates are a property
    of the training context rather than of the catalog (D17, D20).
    """
    bottom, top = state.rep_range
    if bottom > top:
        raise ValueError(f"rep range is inverted: {state.rep_range}")

    if not last_session_sets:
        return _prescribe(state, state.current_load, state.current_reps, Decision.REPEAT)

    # Double progression advances only when every set cleared the bar, so the limiting
    # set decides. Rewarding the best set would advance a user who managed one good set
    # out of four.
    limiting = min(last_session_sets, key=lambda s: (s.reps, s.rir))

    if state.is_estimated:
        return _correct_estimate(state, limiting, available_loads)

    loadable = state.current_load is not None and bool(available_loads)

    if limiting.reps < bottom:
        return _fail(state, available_loads, loadable, walk_difficulty)

    if limiting.reps >= top:
        if limiting.rir < 1:
            # At the ceiling but with nothing left in reserve. Repeat it and earn the
            # reserve before adding load, rather than loading a set already at failure.
            return _prescribe(
                state, state.current_load, top, Decision.HOLD_AT_TOP,
                reset_failures=True,
            )
        return _advance(state, available_loads, loadable, walk_difficulty)

    # Inside the range: add a rep, hold the load. A cleared session clears the failure
    # count, so two failures must be consecutive to trigger a deload.
    return _prescribe(
        state,
        state.current_load,
        min(limiting.reps + 1, top),
        Decision.ADD_REPS,
        reset_failures=True,
    )


def _advance(
    state: ExerciseState,
    available_loads: Sequence[Decimal],
    loadable: bool,
    walk_difficulty: WalkDifficulty | None,
) -> Prescription:
    bottom, top = state.rep_range

    if not loadable:
        # "Increase load" for a bodyweight movement means a harder variant — the
        # substitution graph earning its keep a second time (PRD §8).
        harder = walk_difficulty(state.exercise_id, +1) if walk_difficulty else None
        if harder is None:
            # Nothing harder exists. Keep adding reps past the top rather than stalling.
            return _prescribe(
                state, None, state.current_reps + 1, Decision.HOLD_INCREMENT_TOO_LARGE,
                reset_failures=True,
            )
        return Prescription(
            exercise_id=harder,
            load=None,
            target_reps=bottom,
            decision=Decision.STEP_UP_DIFFICULTY,
            # A node reached across an edge has never been trained against, so its state
            # is a seed, not a measurement (D15).
            next_state=ExerciseState(
                exercise_id=harder, rep_range=state.rep_range, current_load=None,
                current_reps=bottom, consecutive_failures=0, is_estimated=True,
            ),
        )

    assert state.current_load is not None
    step = next_available_load(state.current_load, available_loads)
    if step is None:
        # D13: the next increment is over 20%, or there is nothing heavier. Hold the
        # load and keep adding reps past the top of the range.
        return _prescribe(
            state, state.current_load, state.current_reps + 1,
            Decision.HOLD_INCREMENT_TOO_LARGE, reset_failures=True,
        )
    return _prescribe(state, step, bottom, Decision.INCREASE_LOAD, reset_failures=True)


def _fail(
    state: ExerciseState,
    available_loads: Sequence[Decimal],
    loadable: bool,
    walk_difficulty: WalkDifficulty | None,
) -> Prescription:
    bottom, _ = state.rep_range
    failures = state.consecutive_failures + 1
    if failures < FAILURES_BEFORE_DELOAD:
        return _prescribe(
            state, state.current_load, bottom, Decision.COUNT_FAILURE, failures=failures
        )

    if not loadable:
        easier = walk_difficulty(state.exercise_id, -1) if walk_difficulty else None
        if easier is None:
            return _prescribe(
                state, None, bottom, Decision.COUNT_FAILURE, failures=failures
            )
        return Prescription(
            exercise_id=easier,
            load=None,
            target_reps=bottom,
            decision=Decision.STEP_DOWN_DIFFICULTY,
            next_state=ExerciseState(
                exercise_id=easier, rep_range=state.rep_range, current_load=None,
                current_reps=bottom, consecutive_failures=0, is_estimated=True,
            ),
        )

    assert state.current_load is not None
    # Round down, so the deload is at least 10%. A decrease has no D13 bound; only
    # increases do.
    dropped = round_to_available_load(state.current_load * DELOAD_RATIO, available_loads)
    return _prescribe(state, dropped, bottom, Decision.DELOAD, failures=0)


def _correct_estimate(
    state: ExerciseState, limiting: LoggedSet, available_loads: Sequence[Decimal]
) -> Prescription:
    """D15: the first logged session against a seeded node replaces the guess.

    Not bounded by D13, in either direction. A seed that is 40% off would otherwise cost
    four wasted sessions converging at 10% a time.
    """
    bottom, top = state.rep_range
    cleared = replace(state, is_estimated=False, consecutive_failures=0)

    if limiting.load is None or not available_loads:
        # Non-loadable: nothing to correct, just start the range honestly.
        return _prescribe(
            cleared, None, max(bottom, min(limiting.reps, top)), Decision.CORRECT_ESTIMATE
        )

    if limiting.reps + limiting.rir > MAX_REPS_TO_FAILURE:
        # Too far from failure for e1RM to mean anything (D5), but the load was still
        # demonstrably moved. Anchor on it: a conservative correction beats raising on a
        # legitimate log, and beats leaving the seed in place for another session.
        return _prescribe(
            cleared, round_to_available_load(limiting.load, available_loads), bottom,
            Decision.CORRECT_ESTIMATE,
        )

    e1rm = best_e1rm_estimate(limiting.load, limiting.reps, limiting.rir)
    target = e1rm * rir_to_percent_1rm(TARGET_RIR, top)
    return _prescribe(
        cleared, round_to_available_load(target, available_loads), bottom,
        Decision.CORRECT_ESTIMATE,
    )


def _prescribe(
    state: ExerciseState,
    load: Decimal | None,
    target_reps: int,
    decision: Decision,
    *,
    failures: int | None = None,
    reset_failures: bool = False,
) -> Prescription:
    resolved = 0 if reset_failures else (
        state.consecutive_failures if failures is None else failures
    )
    return Prescription(
        exercise_id=state.exercise_id,
        load=load,
        target_reps=target_reps,
        decision=decision,
        next_state=replace(
            state,
            current_load=load,
            current_reps=target_reps,
            consecutive_failures=resolved,
            is_estimated=state.is_estimated and decision is Decision.REPEAT,
        ),
    )
