"""Weekly plan generation. Pure functions (CLAUDE.md constraint 1).

Greedy with a scoring function, deliberately not a solver: the search space here is a few
dozen exercises over five days, and an ILP would be a dependency and an opaque failure
mode in exchange for an optimum nobody can perceive.

Weekly rather than rolling is a Phase 1 scope decision (D16), not an architectural one.
Nothing below assumes a week beyond taking the days it is given.
"""

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from engine.progression.volume import Landmark

# Working time for one set including its rest. Crude on purpose: the time budget is a
# user's estimate of their own availability, so precision here is false.
MINUTES_PER_SET = 3
SETS_PER_EXERCISE = 3

# D7, prescription side: a set is hard when its target RIR is 3 or less. Everything this
# generator prescribes is hard, which is what makes the MRV and consecutive-day
# invariants assertable at generation time.
TARGET_RIR = 2
REPS_BY_GOAL = {"strength": 5, "hypertrophy": 10}

# Scoring weights. Volume dominates because closing the weekly gap is the job; balance
# breaks ties between muscles that are equally behind.
W_VOLUME = 3.0
W_BALANCE = 1.5
W_EQUIPMENT = 1.0
W_SWAP = 1.0


class Experience(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class Goal(StrEnum):
    STRENGTH = "strength"
    HYPERTROPHY = "hypertrophy"


@dataclass(frozen=True)
class Candidate:
    exercise_id: uuid.UUID
    slug: str
    movement_pattern: str
    primary_muscle: str
    equipment: frozenset[str]
    difficulty: int
    loadable: bool


@dataclass(frozen=True)
class PlanItem:
    exercise_id: uuid.UUID
    slug: str
    movement_pattern: str
    primary_muscle: str
    sets: int
    target_reps: int
    target_rir: int
    load: Decimal | None
    # Resolved at generation and shipped with the plan, never fetched on demand: the
    # occupied-machine swap happens mid-set in a gym basement with no signal (PRD §6).
    substitutes: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class Session:
    day: date
    items: tuple[PlanItem, ...]

    @property
    def hard_sets(self) -> int:
        return sum(i.sets for i in self.items)


@dataclass(frozen=True)
class Plan:
    sessions: tuple[Session, ...]

    def weekly_hard_sets(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self.sessions:
            for i in s.items:
                counts[i.primary_muscle] = counts.get(i.primary_muscle, 0) + i.sets
        return counts


def target_sets(landmark: Landmark, experience: Experience) -> int:
    """Weekly hard sets to aim for. Never above MRV, by construction."""
    if experience is Experience.BEGINNER:
        target = landmark.mev
    elif experience is Experience.INTERMEDIATE:
        target = (landmark.mev + landmark.mav) // 2
    else:
        target = landmark.mav
    return min(target, landmark.mrv)


def generate_plan(
    days: Sequence[date],
    catalog: Sequence[Candidate],
    available_equipment: frozenset[str],
    landmarks: Mapping[str, Landmark],
    time_budget_minutes: int,
    experience: Experience = Experience.INTERMEDIATE,
    goal: Goal = Goal.HYPERTROPHY,
    substitutes_for: Callable[[uuid.UUID], tuple[uuid.UUID, ...]] | None = None,
    previous_loads: Mapping[uuid.UUID, Decimal] | None = None,
    can_express_load: Callable[[Candidate], bool] | None = None,
    swap_penalty: Callable[[uuid.UUID], float] | None = None,
) -> Plan:
    """A week of sessions over `days`, respecting every invariant in CLAUDE.md.

    `days` are calendar dates in the user's own zone, already resolved by the caller —
    the engine has no clock and no timezone (constraint 1, D14).
    """
    if time_budget_minutes < 0:
        raise ValueError("time budget cannot be negative")

    usable = [c for c in catalog if c.equipment <= available_equipment]
    targets = {
        m: target_sets(lm, experience) for m, lm in landmarks.items()
    }
    assigned: dict[str, int] = dict.fromkeys(targets, 0)
    pattern_sets: dict[str, int] = {}
    per_day: dict[date, list[PlanItem]] = {d: [] for d in days}
    day_muscles: dict[date, set[str]] = {d: set() for d in days}
    session_cap = time_budget_minutes // MINUTES_PER_SET
    reps = REPS_BY_GOAL[goal.value]

    ordered_days = sorted(days)
    added = True
    while added:
        added = False
        for day in ordered_days:
            headroom = session_cap - sum(i.sets for i in per_day[day])
            if headroom <= 0:
                continue
            choice = _best(
                day, usable, targets, assigned, pattern_sets, day_muscles, landmarks,
                headroom, per_day, can_express_load, swap_penalty,
            )
            if choice is None:
                continue
            candidate, sets = choice
            per_day[day].append(
                PlanItem(
                    exercise_id=candidate.exercise_id,
                    slug=candidate.slug,
                    movement_pattern=candidate.movement_pattern,
                    primary_muscle=candidate.primary_muscle,
                    sets=sets,
                    target_reps=reps,
                    target_rir=TARGET_RIR,
                    load=(previous_loads or {}).get(candidate.exercise_id),
                    substitutes=substitutes_for(candidate.exercise_id) if substitutes_for else (),
                )
            )
            assigned[candidate.primary_muscle] += sets
            pattern_sets[candidate.movement_pattern] = (
                pattern_sets.get(candidate.movement_pattern, 0) + sets
            )
            day_muscles[day].add(candidate.primary_muscle)
            added = True

    return Plan(
        sessions=tuple(
            Session(day=d, items=tuple(per_day[d])) for d in ordered_days if per_day[d]
        )
    )


def _best(
    day: date,
    usable: Sequence[Candidate],
    targets: Mapping[str, int],
    assigned: Mapping[str, int],
    pattern_sets: Mapping[str, int],
    day_muscles: Mapping[date, set[str]],
    landmarks: Mapping[str, Landmark],
    headroom: int,
    per_day: Mapping[date, list[PlanItem]],
    can_express_load: Callable[[Candidate], bool] | None,
    swap_penalty: Callable[[uuid.UUID], float] | None,
) -> tuple[Candidate, int] | None:
    total = sum(pattern_sets.values()) or 1
    already_today = {i.exercise_id for i in per_day[day]}
    scored: list[tuple[float, str, Candidate, int]] = []

    for c in usable:
        if c.exercise_id in already_today:
            continue
        if c.primary_muscle not in targets:
            continue
        # No muscle group programmed hard on consecutive calendar days (CLAUDE.md, D14).
        # Both neighbours, because days fill round-robin and a later day may already hold
        # work by the time an earlier one is revisited.
        neighbours = day_muscles.get(day - timedelta(days=1), set()) | day_muscles.get(
            day + timedelta(days=1), set()
        )
        if c.primary_muscle in neighbours:
            continue

        gap = targets[c.primary_muscle] - assigned[c.primary_muscle]
        mrv_headroom = landmarks[c.primary_muscle].mrv - assigned[c.primary_muscle]
        sets = min(SETS_PER_EXERCISE, gap, mrv_headroom, headroom)
        if sets <= 0:
            continue

        volume = gap / max(targets[c.primary_muscle], 1)
        balance = 1.0 - pattern_sets.get(c.movement_pattern, 0) / total
        # A loadable exercise the context can actually load is worth more: it is the one
        # that can progress by load rather than only by reps.
        fit = 1.0 if c.loadable and (can_express_load is None or can_express_load(c)) else 0.4
        # Stubbed until Phase 3 has real swap data; the hook exists so scoring does not
        # have to be reshaped when it arrives.
        penalty = swap_penalty(c.exercise_id) if swap_penalty else 0.0

        score = W_VOLUME * volume + W_BALANCE * balance + W_EQUIPMENT * fit - W_SWAP * penalty
        # Slug breaks ties so replay is deterministic, same reason as D6.
        scored.append((-score, c.slug, c, sets))

    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1]))
    return scored[0][2], scored[0][3]
