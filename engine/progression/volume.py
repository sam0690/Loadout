"""Volume landmarks and the fatigue gate (PRD §8). Pure functions.

Landmarks arrive as an argument rather than being read: D18 put them in a table
specifically so the caller loads them and the engine stays I/O-free. `today` is a
parameter for the same reason (CLAUDE.md constraint 1).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

# D7, log side: a set counts as hard when it was actually taken to within 3 of failure.
# The prescription side (target RIR <= 3) is the generator's business, not this module's.
HARD_SET_MAX_RIR = 3

# PRD §8's "4-6 weeks accumulating". A range, not a rule, so: from week 4 a fatigue signal
# triggers it, and week 6 forces it regardless.
DELOAD_WINDOW_OPENS = 4
DELOAD_FORCED_AT = 6

# An e1RM within this fraction of its own recent best is flat, not progressing.
STALL_TOLERANCE = Decimal("0.02")


class Verdict(StrEnum):
    ADD_A_SET = "add_a_set"  # below MEV
    PROGRESS = "progress"  # between MEV and MAV
    HOLD = "hold"  # approaching MRV


class Severity(StrEnum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


@dataclass(frozen=True)
class Landmark:
    mev: int
    mav: int
    mrv: int


@dataclass(frozen=True)
class LoggedSet:
    """One logged set, already attributed to a muscle group.

    `primary_muscle` is singular on purpose: compounds credit their primary only, so
    secondaries are not double-counted into a second muscle's weekly total (PRD §8, D7).
    """

    primary_muscle: str
    reps: int
    rir: int
    day: date


@dataclass(frozen=True)
class HardSession:
    muscle: str
    day: date


@dataclass(frozen=True)
class AbandonedWorkout:
    day: date
    sets_completed: int
    load_used: Decimal | None = None


@dataclass(frozen=True)
class Soreness:
    muscle: str
    severity: Severity
    day: date


@dataclass(frozen=True)
class SessionWork:
    """What a session actually asks of one exercise.

    Separate from 1.2's Prescription because sets are not decided until 1.4; the
    generator composes a prescription and a set count into this, then gates it.
    """

    load: Decimal | None
    reps: int
    sets: int


@dataclass(frozen=True)
class Cap:
    """Upper bounds, never targets.

    The gate returns one of these rather than a modified SessionWork, so applying it can
    only ever reduce. An increase is not a bug a test has to catch — it is unrepresentable
    (build prompt 1.3: structurally enforced, not just conventional).
    """

    max_load: Decimal | None = None
    max_reps: int | None = None
    max_sets: int | None = None
    reasons: tuple[str, ...] = ()

    def merge(self, other: "Cap") -> "Cap":
        """Tightest of each bound. Merging caps can only tighten them."""
        return Cap(
            max_load=_tighter(self.max_load, other.max_load),
            max_reps=_tighter(self.max_reps, other.max_reps),
            max_sets=_tighter(self.max_sets, other.max_sets),
            reasons=self.reasons + other.reasons,
        )


def _tighter[T: (int, Decimal)](a: T | None, b: T | None) -> T | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def weekly_hard_sets(sets: Iterable[LoggedSet]) -> dict[str, int]:
    """Hard sets per muscle group. Logged RIR 0-3 only (D7), primary muscle only."""
    counts: dict[str, int] = {}
    for s in sets:
        if s.rir > HARD_SET_MAX_RIR or s.reps < 1:
            continue
        counts[s.primary_muscle] = counts.get(s.primary_muscle, 0) + 1
    return counts


def verdict(count: int, landmark: Landmark) -> Verdict:
    if count < landmark.mev:
        return Verdict.ADD_A_SET
    if count <= landmark.mav:
        return Verdict.PROGRESS
    return Verdict.HOLD


def is_stalled(e1rm_by_week: Sequence[Decimal], tolerance: Decimal = STALL_TOLERANCE) -> bool:
    """True when the most recent e1RM has not beaten its own recent best.

    PRD §8's progress signal. Two weeks is the shortest series that can show a trend.
    """
    if len(e1rm_by_week) < 2:
        return False
    best_before = max(e1rm_by_week[:-1])
    if best_before <= 0:
        return False
    return (e1rm_by_week[-1] - best_before) / best_before <= tolerance


def should_deload(
    weeks_accumulated: int,
    hard_sets: Mapping[str, int],
    landmarks: Mapping[str, Landmark],
    e1rm_by_week: Sequence[Decimal] = (),
) -> bool:
    """PRD §8's "4-6 weeks accumulating", read as a rule.

    Below week 4 a block is too young to deload. From week 4 a real fatigue signal — any
    muscle at its MRV, or e1RM flat — triggers it. Week 6 forces it regardless, so a block
    can never run long on the absence of a signal.
    """
    if weeks_accumulated >= DELOAD_FORCED_AT:
        return True
    if weeks_accumulated < DELOAD_WINDOW_OPENS:
        return False
    at_mrv = any(
        count >= landmarks[m].mrv for m, count in hard_sets.items() if m in landmarks
    )
    return at_mrv or is_stalled(e1rm_by_week)


def fatigue_cap(
    work: SessionWork,
    muscle: str,
    today: date,
    hard_sessions: Iterable[HardSession] = (),
    abandoned: AbandonedWorkout | None = None,
    soreness: Iterable[Soreness] = (),
) -> Cap:
    """Bounds this muscle's work today, given recent history. Never a target.

    Runs last, after progression has produced a prescription (PRD §8). Takes `work` so a
    proportional rule can be expressed as an absolute bound — Cap stays a set of ceilings,
    which is what makes `apply` unable to increase anything.
    """
    cap = Cap()
    yesterday = today - timedelta(days=1)

    # D14: consecutive calendar days in the user's zone, not a 48h window. The caller has
    # already resolved these to local dates, since the engine has no clock or timezone.
    if any(h.muscle == muscle and h.day == yesterday for h in hard_sessions):
        cap = cap.merge(
            Cap(max_sets=0, reasons=(f"{muscle} was trained hard yesterday",))
        )

    if abandoned is not None and abandoned.day == yesterday:
        # Capped at what was actually completed rather than an invented fraction: the
        # abandoned session is itself the evidence for how much was available.
        cap = cap.merge(
            Cap(
                max_sets=abandoned.sets_completed,
                max_load=abandoned.load_used,
                reasons=("the last workout was abandoned",),
            )
        )

    for s in soreness:
        if s.muscle != muscle:
            continue
        # ponytail: the moderate and severe scalings are chosen, not specified. §8 says
        # only "any of these caps the prescription". Tune once real soreness reports exist.
        if s.severity is Severity.SEVERE:
            cap = cap.merge(Cap(max_sets=0, reasons=(f"{muscle} is severely sore",)))
        elif s.severity is Severity.MODERATE:
            # Halved, rounded down, but never below one set: dropping to zero is what
            # SEVERE is for.
            cap = cap.merge(
                Cap(
                    max_sets=max(1, work.sets // 2),
                    reasons=(f"{muscle} is moderately sore",),
                )
            )

    return cap


def apply(work: SessionWork, cap: Cap) -> SessionWork:
    """Apply a cap. Reduces or leaves alone; it has no path that increases anything."""
    return SessionWork(
        load=_tighter(work.load, cap.max_load) if work.load is not None else None,
        reps=work.reps if cap.max_reps is None else min(work.reps, cap.max_reps),
        sets=work.sets if cap.max_sets is None else min(work.sets, cap.max_sets),
    )
