# Build prompts

Feed these **one at a time**. Each assumes `CLAUDE.md` is in the repo root and `docs/PRD.md` exists. Review and commit between tasks — never queue several of these up.

The acceptance criteria are the important part. They're what turns "looks plausible" into "verifiably correct," and they're what you check before moving on.

---

## Setup

> Read `CLAUDE.md` and `docs/PRD.md` in full. Then, without writing any code, tell me:
> 1. Your understanding of the substitution graph and the three traversal triggers
> 2. Which parts of the PRD you think are underspecified enough to block implementation
> 3. Any place the PRD contradicts itself
>
> I want to correct your model of the project before we build anything.

Do not skip this. If the summary comes back wrong, everything downstream is wrong, and this is the cheapest possible place to find out.

---

# Phase 0 — Catalog and graph

## 0.1 Schema and migrations

> Set up the project skeleton and the Phase 0 database schema.
>
> Create: Python 3.12 project with `uv`, FastAPI dependency (unused for now), SQLAlchemy Core, Alembic, pytest, Hypothesis, ruff, mypy. Docker Compose with Postgres 16 only.
>
> Write Alembic migrations for the Phase 0 tables in PRD §7: `exercises`, `exercise_edges`, `equipment`, `equipment_aliases`, `gym_archetypes`, `training_contexts`. Follow the PRD's column definitions exactly — if you think a column is wrong, tell me instead of changing it.
>
> Add indexes you can justify. For each one, state the query it serves in a comment.
>
> Acceptance: `alembic upgrade head` then `downgrade base` runs clean both directions. `docker compose up` gives a working database. No API code, no models beyond table definitions.

## 0.2 Equipment taxonomy seed

> Build the canonical equipment taxonomy as a YAML seed file plus a loader.
>
> Cover home equipment (bodyweight, bands, adjustable dumbbells, fixed dumbbells, kettlebell, pull-up bar, flat bench, adjustable bench, barbell, plates, suspension trainer) and commercial gym machines (cable stack, smith machine, leg press, seated row, lat pulldown, chest press, pec deck, leg curl, leg extension, hack squat).
>
> Each entry: slug, class, movement_patterns it supports, is_fixed_path. Include a brand alias list for machines — Hammer Strength, Life Fitness, Technogym, Cybex naming variants.
>
> The loader must be idempotent: running it twice changes nothing. Unknown aliases on ingest raise rather than silently creating rows.
>
> Acceptance: loader is idempotent (test it), every machine has at least two aliases, `mypy --strict` clean.

## 0.3 Exercise catalog ingest

> Build an ingest pipeline for the exercise catalog from `free-exercise-db` (GitHub, JSON).
>
> Steps: fetch raw → normalize muscle names to our taxonomy → normalize equipment through the alias table → dedupe by (movement_pattern, equipment, name similarity) → emit a review file of anything ambiguous rather than guessing.
>
> Target ~80 exercises covering all movement patterns, not the full set. Quality over coverage. The review file is a feature — I want to hand-check the ambiguous cases.
>
> Structure as separate `fetch`, `normalize`, `load` stages that can run independently (`uv run python -m ingest.fetch` and so on), with raw data cached to disk so re-running normalization doesn't re-fetch.
>
> Acceptance: `uv run python -m ingest` populates the catalog. Every exercise has a movement_pattern and non-empty primary_muscles. Ambiguous cases land in `review.csv` instead of the database.

## 0.4 Substitution graph traversal

> Implement graph traversal in `engine/graph/`. Pure functions, per constraint 1 in CLAUDE.md.
>
> `find_substitutes(exercise_id, available_equipment, reason, max_depth=3)` returns ranked candidates.
>
> Traversal order depends on reason:
> - `unavailable_now` → `lateral_equivalent` edges first, then `equipment_downgrade`
> - `unavailable_owned` / `unavailable_here` → `equipment_downgrade` first
>
> Never cross movement patterns. Never return an exercise whose equipment isn't a subset of available. Rank by fewest hops, then smallest difficulty delta.
>
> The recursive CTE goes in `queries/` as raw SQL. The pure function takes the already-loaded graph as an argument — the query is called by the caller, not by the engine.
>
> Acceptance: Hypothesis property tests proving termination within max_depth, movement-pattern invariance, and equipment-subset invariance across randomly generated graphs and equipment sets.

## 0.5 Hand-authored edges

> Generate a starter edge set for the seeded catalog and write it to a reviewable YAML file — not directly to the database.
>
> For each movement pattern, build the equipment downgrade chain from most-equipped to bodyweight, plus difficulty steps within bodyweight variants, plus lateral equivalents between same-difficulty different-equipment options.
>
> I will review and correct this by hand before it loads. Flag anything you're unsure about with a comment rather than guessing.
>
> Acceptance: every exercise reachable from at least one other node. Every pattern has a complete path to a bodyweight option. No orphans.

---

# Phase 1 — The engine

## 1.1 Progression primitives

> Implement `engine/progression/primitives.py`. Pure functions, no I/O.
>
> - `epley_e1rm(weight, reps)` and `brzycki_e1rm(weight, reps)`
> - `rir_to_percent_1rm(rir, reps)` using the table in D5 — indexed by `reps + rir`, raises above 15
> - `best_e1rm_estimate(weight, reps, rir)` — cross-check both, take the higher, per PRD §8
> - `round_to_available_load(target, equipment)` — plate math and dumbbell increments differ; a 2.5kg jump is impossible with fixed dumbbells
>
> `round_to_available_load` is the one with real edge cases. Per D13: increase only if the next increment is ≤20% of current load, otherwise hold and add reps past the range top. Property-test both bounds — `max(10%, one increment)` and the hard 20% ceiling.
>
> Acceptance: unit tests against the worked examples in the PRD. Property test that e1RM is monotonically increasing in both weight and reps.

## 1.2 Double progression state machine

> Implement `engine/progression/double_progression.py`.
>
> `next_prescription(exercise_state, last_session_sets, equipment) -> Prescription`
>
> Implement the state machine in PRD §8 exactly: rep progression within range, load increase at top of range with RIR ≥ 1 subject to D13's two bounds, failure counting, 10% deload after two consecutive failures. For non-loadable exercises, "increase load" means walking a `difficulty_step` edge — take a callback for graph traversal rather than importing the graph module directly.
>
> Acceptance: property test that load never jumps more than `max(10%, one increment)` and never more than 20%, both asserted separately, including through the deload path. Test the `is_estimated` exemption (D15) and the non-loadable branch separately.

## 1.3 Volume landmarks and fatigue gate

> Implement `engine/progression/volume.py`.
>
> Weekly hard-set counting per muscle group (logged RIR 0–3 only, compounds credit primary muscle only — see D7 for the prescribed-vs-logged split), comparison against MEV/MAV/MRV (values in D11), deload triggering after 4–6 accumulating weeks.
>
> Then the fatigue gate: given recent events, cap any prescription that would train a muscle group hard on the calendar day after the last hard session in the user's zone (D14 — day-granular, not 48h), or follow an abandoned workout, or contradict reported soreness.
>
> The gate runs last and can only reduce, never increase. Make that structurally enforced, not just conventional.
>
> Acceptance: property test that gate output is always ≤ input prescription on every dimension.

## 1.4 Plan generator

> Implement `engine/generator/`. This is the constraint solver.
>
> Given a training context, time budget, session count, experience level, and goal, produce a week of sessions (weekly per D16 — a Phase 1 scope decision; don't build anything that assumes it's architectural) satisfying: weekly volume targets per muscle group, movement pattern balance, equipment availability, time budget, and no consecutive-day overlap on the same muscle group.
>
> Greedy with a scoring function is fine — do not reach for an ILP solver. Score candidates on volume gap closed, pattern balance, equipment fit, and user swap history (stub the last one, it needs Phase 3 data).
>
> Precompute the substitution set for each prescribed exercise and include it in the output — the client needs these offline, per PRD §6.
>
> Acceptance: Hypothesis test generating 1000 plans across random contexts, asserting every invariant in CLAUDE.md's testing section. This is the test that matters most in the project.

---

# Phase 2 — Ship it

## 2.1 Event ingest

> Implement the events table, `POST /events` (batch), and idempotent upsert on client UUID. Projections for `exercise_state` rebuilt from the log, plus a `rebuild_projections()` function.
>
> Acceptance: submitting the same batch twice produces identical state. Dropping and rebuilding projections from the event log reproduces state exactly. Test both.

## 2.2 API surface

> FastAPI routes: auth (email magic link, no passwords), training contexts CRUD, `POST /plans` returning 202 + job id, `GET /jobs/{id}`, `GET /plans/current`, `POST /events`.
>
> Plan generation goes through RQ. Everything else is synchronous.
>
> Acceptance: OpenAPI schema generates a clean TS client. Integration tests cover the full generate → poll → fetch → log cycle.

## 2.3 Frontend

> Next.js App Router. Screens: onboarding (context setup via archetype picker), current plan, session logger, history.
>
> The logger is the screen that matters — it's used mid-set, one-handed, possibly sweaty. Large tap targets, minimal chrome, no modal dialogs. Writes go to IndexedDB first and render optimistically, then sync.
>
> Read `/mnt/skills/public/frontend-design/SKILL.md` before starting on visual design.
>
> Acceptance: full session loggable with the network tab throttled to offline; events flush correctly on reconnect.

---

# Later phases

Do not start these until Phase 2 has real users producing real events. Phase 3 in particular is meaningless against synthetic data.

- **2.5** Gym archetypes, machine catalog, occupied-equipment flow
- **3** dbt marts, swap-rate analysis, feedback into generator scoring
- **4** React Native, offline sync, conflict resolution
- **5** LLM feedback parsing and explanation, behind a feature flag

---

## Prompting notes

**When Claude drifts.** "Re-read CLAUDE.md constraint 1 and tell me whether the code you just wrote satisfies it." Usually more effective than describing the violation yourself.

**When output is too large to review.** Stop and split. Code you didn't read is code you can't debug, and the whole value of this project is that you understand it deeply enough to talk about it.

**When you disagree with an approach.** Ask for the reasoning before overriding. Sometimes it's right and you learn something; when it isn't, the reasoning shows you exactly which constraint to restate.

**Update CLAUDE.md as you go.** Every time you correct the same mistake twice, that correction belongs in the file. It's a living document, and a good one is the difference between Claude Code being useful and being a liability on a project this size.
