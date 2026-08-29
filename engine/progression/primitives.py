"""Progression arithmetic. Pure functions (CLAUDE.md constraint 1).

Decimal throughout, not float: loads are NUMERIC in the database and 2.5kg steps
accumulate error in binary floating point, which matters when the difference between
holding and progressing is a 20% threshold test.
"""

from collections.abc import Iterable, Sequence
from decimal import Decimal

# D5. Indexed by reps-to-failure (reps + RIR), not by both separately: a set of 8 at
# RIR 2 is a 10-rep max. One dimension, monotonic, trivially property-testable.
PERCENT_1RM: dict[int, Decimal] = {
    1: Decimal("1.00"), 2: Decimal("0.95"), 3: Decimal("0.92"), 4: Decimal("0.89"),
    5: Decimal("0.86"), 6: Decimal("0.84"), 7: Decimal("0.81"), 8: Decimal("0.79"),
    9: Decimal("0.76"), 10: Decimal("0.74"), 11: Decimal("0.71"), 12: Decimal("0.69"),
    13: Decimal("0.67"), 14: Decimal("0.65"), 15: Decimal("0.63"),
}
MAX_REPS_TO_FAILURE = max(PERCENT_1RM)

# D13. Both bounds, and the second is not implied by the first: "one increment" alone
# is unbounded, so a rack that jumps 10kg to 30kg would satisfy it with a 200% rise.
TARGET_INCREASE_RATIO = Decimal("0.10")
MAX_INCREASE_RATIO = Decimal("0.20")

# Brzycki's denominator collapses as reps approach 37 and the estimate is not credible
# well before that. Capped at the same place D5 stops caring.
MAX_BRZYCKI_REPS = 15


class RepsOutOfRange(ValueError):
    """Reps or reps-to-failure outside the range where the estimate means anything.

    Raised rather than clamped: a silent default here becomes a prescribed load
    (CLAUDE.md, fail loudly in the engine).
    """


def _check_positive(weight: Decimal, reps: int) -> None:
    if reps < 1:
        raise RepsOutOfRange(f"reps must be at least 1, got {reps}")
    if weight < 0:
        raise ValueError(f"weight cannot be negative, got {weight}")


def epley_e1rm(weight: Decimal, reps: int) -> Decimal:
    """PRD §8. Accurate to roughly 3% in the 2-10 rep range."""
    _check_positive(weight, reps)
    return weight * (1 + Decimal(reps) / 30)


def brzycki_e1rm(weight: Decimal, reps: int) -> Decimal:
    _check_positive(weight, reps)
    if reps > MAX_BRZYCKI_REPS:
        raise RepsOutOfRange(
            f"brzycki is not credible at {reps} reps (max {MAX_BRZYCKI_REPS})"
        )
    return weight * 36 / (37 - Decimal(reps))


def rir_to_percent_1rm(rir: int, reps: int) -> Decimal:
    """Fraction of 1RM a set of `reps` at `rir` represents (D5)."""
    if rir < 0:
        raise ValueError(f"rir cannot be negative, got {rir}")
    if reps < 1:
        raise RepsOutOfRange(f"reps must be at least 1, got {reps}")
    total = reps + rir
    if total > MAX_REPS_TO_FAILURE:
        raise RepsOutOfRange(
            f"{reps} reps at RIR {rir} is {total} reps to failure; e1RM is not "
            f"meaningful past {MAX_REPS_TO_FAILURE}"
        )
    return PERCENT_1RM[total]


def best_e1rm_estimate(weight: Decimal, reps: int, rir: int) -> Decimal:
    """Epley cross-checked against the RIR table, higher wins (PRD §8).

    Brzycki is available but deliberately not in this maximum: §8 names Epley and the
    RIR table specifically, and quietly folding in a third estimator would change every
    prescription without the PRD saying so.
    """
    from_reps = epley_e1rm(weight, reps)
    from_rir = weight / rir_to_percent_1rm(rir, reps)
    return max(from_reps, from_rir)


def barbell_loads(
    bar_weight: Decimal, plate_pairs: Iterable[Decimal], ceiling: Decimal
) -> list[Decimal]:
    """Loads a barbell can express: bar weight plus every reachable pair combination.

    D17's derived case. Plates live in the training context, not the catalog, which is
    why this takes them as an argument rather than reading an equipment row.
    """
    plates = sorted({Decimal(p) for p in plate_pairs if p > 0})
    reachable = {bar_weight}
    frontier = {bar_weight}
    while frontier:
        nxt = set()
        for load in frontier:
            for p in plates:
                candidate = load + 2 * p
                if candidate <= ceiling and candidate not in reachable:
                    reachable.add(candidate)
                    nxt.add(candidate)
        frontier = nxt
    return sorted(reachable)


def round_to_available_load(target: Decimal, loads: Sequence[Decimal]) -> Decimal:
    """Largest expressible load not above `target`.

    Rounds down, never up: rounding up can push an increase past D13's ceiling, and a
    slightly light set costs one session while an overshoot costs a failed one. If the
    target is below everything expressible, the lightest load is all there is.
    """
    if not loads:
        raise ValueError("no expressible loads; this exercise is not loadable")
    below = [load for load in sorted(loads) if load <= target]
    return below[-1] if below else min(loads)


def next_available_load(current: Decimal, loads: Sequence[Decimal]) -> Decimal | None:
    """The next load up, or None when D13 says hold and add reps instead.

    None is not a failure. It is the answer at the bottom of a fixed-dumbbell rack,
    where 10kg to 12.5kg is 25% and no amount of arithmetic makes it smaller.
    """
    if not loads:
        raise ValueError("no expressible loads; this exercise is not loadable")
    above = [load for load in sorted(loads) if load > current]
    if not above:
        return None
    step = above[0]
    if current <= 0:
        return step
    if (step - current) / current > MAX_INCREASE_RATIO:
        return None
    return step
