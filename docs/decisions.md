# Decisions

Resolutions to gaps and contradictions found in `docs/PRD.md` and `CLAUDE.md`.
One entry per decision. `APPLIED` = folded into the PRD, build against it.
All 16 are APPLIED as of 2026-08-29; D13–D16 were accepted with amendments,
recorded inline below.

Last updated: 2026-08-29

---

## D1 — `exercises.equipment` is `text[]` of canonical slugs — APPLIED

§7 shows `equipment text[]` and then argues free-text equipment is
catastrophic. Both are true: the column stays `text[]`, but every element must
be an `equipment.slug`. Ingest resolves brand names through
`equipment_aliases` or raises; it never writes an unrecognized string.

`text[]` over `uuid[]` because Postgres cannot FK an array either way, so
uuid buys no referential integrity — and the recursive CTE stays readable
with slugs in it, which CLAUDE.md asks for explicitly.

Validation is at the ingest boundary, not in the database. A CHECK constraint
against `equipment` can't be written over an array without a trigger, and a
trigger is more machinery than a loader assertion.

## D2 — `training_contexts.user_id` has no FK until Phase 2 — APPLIED

Column is `uuid not null`, no foreign key in Phase 0, because there is no
users table until auth lands in 2.2. The FK is added in the Phase 2 auth
migration. Nullable was the alternative and it is worse: it pushes a null
check into every downstream query forever to save one line of migration later.

Same situation, no FK, for `gym_archetypes.equipment_ids`,
`training_contexts.equipment_added` and `equipment_removed` — Postgres cannot
FK array elements. Integrity for those is enforced by the loader.

## D3 — Movement pattern taxonomy (closed set of 15) — APPLIED

The `movement_pattern` column, `equipment.movement_patterns`, and the
"never crosses movement patterns" invariant all need this enumerated.

Compound:
`horizontal_press`, `vertical_press`, `horizontal_pull`, `vertical_pull`,
`squat`, `hinge`, `lunge`

Isolation:
`elbow_flexion`, `elbow_extension`, `shoulder_abduction`, `knee_flexion`,
`knee_extension`, `calf_raise`

Trunk:
`core_anti_extension`, `core_anti_rotation`

Isolation patterns are in the set because per-muscle volume landmarks (D11)
cannot be hit for biceps, side delts or calves from compounds alone.

Stored as `text` with a CHECK constraint, not a Postgres enum — adding a value
to an enum in a migration is more painful than editing a CHECK, and we will
add patterns.

## D4 — Muscle group taxonomy (closed set of 16) — APPLIED

Normalization target for ingest, and the key for volume landmarks.

`chest`, `front_delts`, `side_delts`, `rear_delts`, `lats`, `upper_back`,
`traps`, `biceps`, `triceps`, `forearms`, `quads`, `hamstrings`, `glutes`,
`calves`, `abs`, `spinal_erectors`

## D5 — RIR→%1RM is one-dimensional on reps-to-failure — APPLIED

The PRD says "the standard RPE table" and several published charts disagree.
We use the reps-in-reserve equivalence: a set of 8 at RIR 2 is a 10-rep max.
So the table is indexed by `reps + rir`, not by both separately. One
dimension, monotonic, trivially property-testable.

| reps+RIR | %1RM | | reps+RIR | %1RM |
|---|---|---|---|---|
| 1 | 100 | | 9 | 76 |
| 2 | 95 | | 10 | 74 |
| 3 | 92 | | 11 | 71 |
| 4 | 89 | | 12 | 69 |
| 5 | 86 | | 13 | 67 |
| 6 | 84 | | 14 | 65 |
| 7 | 81 | | 15 | 63 |
| 8 | 79 | | | |

Above 15 reps-to-failure, `rir_to_percent_1rm` raises. §8 already says e1RM
degrades past 10 reps; past 15 the number is not worth returning, and
CLAUDE.md says fail loudly rather than return a silent default.

## D6 — `delta` semantics and traversal tiebreak — APPLIED

`delta = difficulty(to) - difficulty(from)`, signed, for every edge type.
`lateral_equivalent` is 0 by definition. `equipment_downgrade` is usually
negative but not required to be — a machine-to-free-weight downgrade can be
harder.

Ranking of candidates in `find_substitutes`, in order:
1. fewest hops
2. smallest absolute cumulative delta
3. `slug` ascending

The third key exists only for determinism. Engine functions are replayed
against history to diff engine versions (CLAUDE.md constraint 1), and that is
worthless if ties order arbitrarily.

## D7 — "Hard set" has a prescription-side and a log-side definition — APPLIED

CLAUDE.md requires every *generated plan* to satisfy "weekly hard sets never
exceed MRV" and "no muscle group programmed hard on consecutive days". But §8
defines a hard set by *logged* RIR 0-3, which the generator cannot know. The
invariant was untestable at generation time.

- **Prescribed hard set:** target RIR <= 3. The generator asserts the MRV and
  consecutive-day invariants against these.
- **Logged hard set:** actual RIR 0-3. Projections and volume landmarks count
  these.

Compounds credit their primary muscle only, both sides. Unchanged from §8.

## D8 — LLM feedback `confidence` is an enum, not a float — APPLIED

§9's example schema returned `"confidence": 0.8`. It is now
`"high" | "medium" | "low"`.

**The reason is calibration, not the numeric boundary.** Self-reported LLM
confidence floats are not calibrated — 0.8 does not mean 80%, and treating it
as a threshold gives a false sense of precision. Three buckets are honest
about what the signal is worth. Threshold behaviour lives in the engine.

Do **not** read constraint 4 as "the LLM may not emit any numeral". It means
the LLM never produces a **training prescription** — loads, reps, sets,
deloads, or a fatigue-gate override. A confidence score is not one of those.
Over-applying the constraint would rule out things that are fine, such as
returning a count of implicated movement patterns.

## D9 — The two deloads do not interact — APPLIED

§8 has a per-exercise deload (2 consecutive failures, -10% load) and a weekly
volume deload (4-6 accumulating weeks, drop to MEV). They run at different
levels and both can fire in the same week.

- A volume deload week sets prescribed sets to MEV and holds load flat. It
  does **not** reset per-exercise failure counters.
- A per-exercise deload still fires during a volume deload week if that
  exercise hits 2 consecutive failures.
- Load is never reduced twice for the same failure pair.

## D10 — Training context equipment resolution — APPLIED

```
resolved = (archetype.equipment_ids | equipment_added) - equipment_removed
```

Removal is applied last and wins over addition. Order-independent and
idempotent. A `null` archetype starts from the empty set.

The engine takes the already-resolved set as an argument. Resolution is the
caller's job, same rule as graph loading (CLAUDE.md constraint 1).

## D11 — Volume landmark starting defaults — APPLIED

Weekly hard sets per muscle group. Published-style starting values, per D4's
taxonomy. Per-user adjustment from recovery signals is Phase 3 — these are
constants until real events exist to adjust them with.

| muscle | MEV | MAV | MRV | | muscle | MEV | MAV | MRV |
|---|---|---|---|---|---|---|---|---|
| chest | 8 | 14 | 22 | | biceps | 8 | 14 | 26 |
| front_delts | 6 | 12 | 16 | | triceps | 6 | 12 | 18 |
| side_delts | 8 | 16 | 26 | | forearms | 4 | 10 | 20 |
| rear_delts | 6 | 14 | 24 | | quads | 8 | 16 | 20 |
| lats | 10 | 16 | 25 | | hamstrings | 6 | 12 | 20 |
| upper_back | 10 | 18 | 25 | | glutes | 0 | 12 | 16 |
| traps | 4 | 12 | 26 | | calves | 8 | 16 | 25 |
| abs | 0 | 16 | 25 | | spinal_erectors | 6 | 12 | 18 |

## D12 — Phase 0 exit criterion is bounded by a real archetype — APPLIED

§10's "returns valid substitutions for every equipment subset" is not
achievable as literally written. `vertical_pull` and `horizontal_pull` have no
true zero-equipment terminal — pulling requires something to pull on — and
`knee_flexion` is close to the same problem.

Restated:

- Every movement pattern reaches a terminal node whose equipment is a subset
  of the `minimal_apartment` archetype.
- For an equipment set with no reachable terminal in a pattern,
  `find_substitutes` raises `NoSubstituteFound`. It does not return an empty
  list. CLAUDE.md: a missing exercise raises rather than returning an empty
  plan.

---

# Accepted with amendments — 2026-08-29

These four amend a CLAUDE.md architectural constraint or close a PRD §12 open
question. All are now settled. The amendment on each is the reviewer's, not
the original proposal.

## D13 — Load increase is bounded twice: relative and absolute — APPLIED

**Problem.** CLAUDE.md made "load never increases more than 10%
session-over-session" absolute. Fixed dumbbells go 10kg to 12.5kg, which is
25%. The invariant and the hardware could not both hold.

**Amendment (accepted).** "One equipment increment" alone is unbounded — a
rack that jumps 10kg to 30kg would satisfy it with a 200% increase. So there
is a hard ceiling on top of the relative rule.

**The rule.**

> Increase load only if the next available increment is ≤20% of current load.
> Otherwise hold load and continue adding reps past the top of the range until
> the increment is proportionally smaller.

**The invariant.**

> Load never increases by more than `max(10%, one available equipment
> increment)`, and never by more than 20% under any circumstance.

Both bounds are encoded in the 1.1 and 1.2 property tests — the second is not
implied by the first and needs its own assertion.

The only exception is a state flagged `is_estimated` (D15), which may correct
past both bounds exactly once.

**Known ceiling, unresolved.** At the bottom of a fixed-dumbbell rack the
escape hatch does not open. 12.5/10 is 25% no matter how many reps get added,
and the ratio never improves while load is held — so a user on 10kg dumbbells
with a 12.5kg next rung accumulates reps forever and never advances load. The
rule is correct for the common case and stalls in this one. Options when it
shows up in Phase 1: allow a single sanctioned >20% jump when reps exceed
range top by some margin, or route the progression through a
`difficulty_step` / unilateral variant instead. Not deciding it now — it needs
a real catalog to reason about.

## D14 — Fatigue gate uses calendar day, not 48 hours — APPLIED

**Problem.** §8 asked "trained hard within 48h?" while CLAUDE.md's invariant
was "no muscle group programmed hard on consecutive calendar days". They
disagreed in both directions: Mon 6am to Tue 8pm is 62 hours (passes 48h) but
consecutive days (fails the invariant); Fri 8pm to Sun 6am is 34 hours (fails
48h) but not consecutive days (passes it).

**The rule.** Consecutive calendar days in the user's IANA zone. The 48h
language is removed from §8.

**Rationale to record:** plan generation is day-granular. A plan assigns
sessions to days, not to timestamps, so an hour-precision gate is false
precision over a decision that was never made at that resolution. It is also
what the property test asserts and what a user can predict without arithmetic.

## D15 — State is seeded across an edge, never shared, and flagged — APPLIED

**Problem.** §6 step 5 asserted that progression state is carried to a
substitute. §12 listed the same thing as open and said carrying e1RM across a
fixed-path/free-weight boundary is wrong. `lateral_equivalent` edges span
different equipment by definition, so the flow §6 called demo-worthy was
exactly the case §12 doubted. The same question recurs for non-loadable
`difficulty_step` progression, since `exercise_state` is keyed
`(user_id, exercise_id)`.

**The rule.** State is per `exercise_id` and is never shared. On first arrival
at a node reached by an edge, seed that node's state from the source,
adjusted by the edge:

- `lateral_equivalent` — seed at parity
- `difficulty_step` — seed adjusted by `delta`
- `equipment_downgrade` — seed adjusted by `delta`, and additionally by a
  per-equipment-class multiplier when the edge crosses `is_fixed_path`

**Amendment (accepted).** Seeded state carries `is_estimated = true` on
`exercise_state`. While that flag is set, the first logged session may correct
load beyond D13's bounds — in either direction, and by any amount. The flag
clears after that one session and normal bounds resume.

Without the exception a bad seed converges at 10% per session, so a seed that
is 40% off costs four wasted sessions. A seed is a guess about a node the user
has never trained; the first real data point should replace it, not nudge it.

This is the one sanctioned violation of D13 and the property tests must exempt
exactly this transition — prior state `is_estimated`, one session — and
nothing else.

The `is_fixed_path` multiplier has no data behind it. Ship it as 1.0 and
revisit in Phase 3 when swap data exists.

§6 step 5 is rewritten; it previously asserted the opposite.

## D16 — Weekly generation, for Phase 1 only — APPLIED

**Problem.** §12 asked weekly vs. rolling next-session generation and left it
open. Build prompt 1.4 quietly assumed weekly.

**The rule.** Weekly for Phase 1. The volume landmark invariants (MEV, MAV,
MRV) are defined over a week and are far cheaper to assert against a week that
exists as an object than against a rolling window. Legibility to the user is
the tiebreak.

**This is a Phase 1 scope decision, not a permanent one.** Rolling generation
stays an open question and §12 keeps it. Revisit when Phase 3 data shows how
often a generated week survives contact with reality — if weeks are routinely
abandoned by Wednesday, the weekly object is the wrong unit and the decision
should flip. Do not build anything that assumes weekly generation is
architectural.

---

# Decided during Phase 0.1 planning — 2026-08-29

## D17 — `equipment.load_increments numeric[]`, nullable — APPLIED

D13's rule needs to know what loads a piece of equipment can actually express, and
the PRD's `equipment` table had no column for it. Added in the 0.1 migration rather
than backfilled, so 0.2's YAML seed can populate it in the same pass.

Sorted ascending. The null/empty distinction carries meaning and both are used:

- `NULL` — **derived**. A barbell's expressible loads are bar weight plus available
  plate pairs, and the plate set varies by training context, so the list cannot be
  enumerated on the equipment row. Computed in `round_to_available_load` at 1.1.
- `{}` — **not loadable**. Bodyweight, pull-up bar, suspension trainer.
- populated — an enumerated rack, e.g. fixed dumbbells `{5,7.5,10,12.5,...}`.

Without the distinction a barbell and a pull-up bar would both be `{}` and 1.1 could
not tell "figure it out" from "there is nothing to figure out".

## D18 — `muscle_groups` is a table, seeded in the 0.1 migration — APPLIED

D4's 16 slugs and D11's MEV/MAV/MRV values live in a table (`slug` PK, `mev`, `mav`,
`mrv`) rather than as a Python constant, seeded directly in the migration since the
data is small, closed, and unchanging — no loader, no YAML.

**The engine still does not read it.** CLAUDE.md constraint 1 stands: the caller
loads landmarks and passes them into `engine/progression/volume.py` at 1.3. The table
is a seed and the eventual home for per-user overrides in Phase 3, not a dependency
of the engine.

Note it gives no referential integrity for `exercises.primary_muscles`, which is a
`text[]` — Postgres cannot FK array elements, same situation as D1 and D2. Ingest
validates against it and raises.

## D19 — Git, and no Claude attribution in commits — APPLIED

The repo is initialized with git; the four markdown files are committed as their own
baseline before any code lands, so the doc work is reviewable separately from 0.1.

Commit messages carry **no Claude attribution** — no `Claude-Session:` trailer, no
`Co-Authored-By`, no mention in the body. Applies to every commit in this repo.
