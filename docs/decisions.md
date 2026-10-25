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

## D20 — One `dumbbells` row, not adjustable-vs-fixed — APPLIED

0.2 seeded `adjustable_dumbbells` and `fixed_dumbbells` as separate canonical rows.
That is wrong, and 0.3's ingest is where it shows: `free-exercise-db` has 123 rows whose
equipment is just `"dumbbell"`, and there is no correct single slug to map them to.

`exercises.equipment` is checked as a **subset** of the context's equipment. Two rows
means a dumbbell bench press must name one of them, and is then unavailable to a user
holding the other — a home user with adjustables gets nothing from the entire
fixed-dumbbell catalog. The exercise requires *a dumbbell*; which rack the user owns is
a property of their training context, which is what 0.2's own seed comment already said.

So: one `dumbbells` row, with the adjustable and fixed variants as aliases, and
`load_increments: null` — derived from the context, per D17.

**Consequence for Phase 1, not resolved here.** Nothing currently lets a training
context declare its actual rack, so `round_to_available_load` has nowhere to read
increments from for dumbbells. `training_contexts` holds `equipment_added` /
`equipment_removed` as bare uuid arrays with no per-item detail. 1.1 needs either a
per-context increment override or a sensible default rack. Flagging now; deciding when
1.1 is written and the shape of `round_to_available_load` is known.

## D21 — A training context declares its own loads — APPLIED

D20 left this open: nothing let a context say what its rack actually is, so
`round_to_available_load` had no increments to read for dumbbells. 1.1 and 1.2 both take
`available_loads` as a parameter, which is the right shape for a pure function, but
nothing could supply it.

**Catalog default plus sparse override.** `equipment.load_increments` carries a typical
rack as a documented assumption, and `training_context_loads` holds a row only where a
context actually differs. No row means the catalog default is fine.

This softens D20's "null means derived" for `dumbbells` specifically. The stricter
reading — raise when a context has not declared a rack — is more consistent, but it puts
a rack enumeration in front of the user's first plan, and PRD §12 already names
onboarding friction as a thing that costs conversion. A typical rack that is sometimes
slightly wrong beats no plan at all, and the override exists for the user who cares.

`barbell` keeps `null`. It is genuinely derived from bar weight plus whichever plate
pairs the context owns and cannot be enumerated on a catalog row at all.

**The arrays stay.** D10's `(preset | added) - removed` rule is unchanged;
`training_context_loads` sits beside it rather than replacing it. Normalising the whole
thing into one join table would fix the referential-integrity gap D2 and D10 both note,
but it rewrites a settled decision to solve a problem that has not bitten yet.

```
training_context_loads (
  training_context_id uuid  -> FK training_contexts
  equipment_id        uuid  -> FK equipment
  load_increments     numeric[] null   -- overrides equipment.load_increments
  bar_weight          numeric   null   -- only meaningful for a bar
  primary key (training_context_id, equipment_id)
)
```

A row with both columns null asserts nothing and is a mistake, so a CHECK rejects it.

## D22 — Hand-authored bodyweight terminals — APPLIED, AMENDED BY D30

> **Amended.** The seven gaps below were real and are closed. An eighth — `vertical_pull`
> — was never in the list, because the catalog wrongly claimed a chin-up needs no
> equipment. D12 had said pulling has no zero-equipment terminal and was right; D30
> corrects the data, accepts the gap, and reports it to the user rather than hiding it.

D12 recorded that seven movement patterns had no zero-equipment terminal, so a user with
nothing got `NoSubstituteFound` for `calf_raise`, `elbow_flexion`, `horizontal_pull`,
`knee_extension`, `lunge`, `shoulder_abduction` and `vertical_press` — half the catalog,
in exactly the minimal-equipment case PRD §1 calls the sharpest differentiator against
Fitbod. Closed two ways.

**Two were ingest bugs, not missing data.** `ingest/taxonomy.py` matched name keywords
most-specific-first, and two pairs were in the wrong order: "Handstand Push-Ups" hit
`push-up` and became a `horizontal_press` before ever reaching the vertical rule, and
"Step-up with Knee Raise" hit `knee raise` and became `core_anti_extension`. The second
was caught by the pattern/muscle consistency gate and sent to review; the first was not,
because front delts are plausible for a horizontal press too. Both rules moved.

**The rest are authored, in `seeds/exercise_terminals.yaml`.** free-exercise-db has no
bodyweight calf raise, no sissy squat and no pike push-up — only stretches with those
words in the name. Nine entries, loaded beside the ingested catalog rather than inside
it, since they are not derived from any source. `ingest.load.full_catalog()` is the one
definition of what the catalog contains, because the loader converges on exactly that set
and anything left out of it gets deleted.

**Three of the nine are compromises and say so in the file.** A horizontal pull needs
something to pull on, and a side delt needs external resistance; lying prone and lifting
the arms, or resisting one arm with the other, trains the right muscle with the wrong
stimulus. `bodyweight_self_resisted_curl` in particular cannot progress under double
progression at all, because its load is unmeasurable — it will sit at the bottom of its
chain forever. They are terminals so the pattern has one, not because they are good
programming.

**The real fix, not done here.** The catalog models equipment a user owns and has no way
to say "a doorway", "a table" or "a sturdy chair", which is what an inverted row and a
Bulgarian split squat actually need. Modelling household objects as equipment would close
these properly and is worth considering before the Phase 2 launch, since the launch cohort
is precisely the people who have a table and no gym.

89 exercises, 216 edges, every pattern reaching a terminal from every node.

## D23 — Magic-link auth, stateless sessions — APPLIED

The build prompt says email magic link, no passwords. Two halves with different storage
models, deliberately.

**The link is stateful.** `magic_links` stores a sha256 of the token, never the token, so
a leaked database hands out no logins. Single use, enforced by `consumed_at`, and valid
for 15 minutes. Single-use is the property that matters and a self-contained token cannot
express it.

**The session is a stateless JWT.** No session table and no per-request database hit.

**The consequence, stated plainly: there is no revocation.** A leaked or mis-delivered
session token stays valid until it expires, and the only lever is the 7-day lifetime. If
revocation is ever needed it means a denylist table — which is the table this choice
avoided, so the trade would be reversed rather than extended. Worth revisiting before the
cohort grows beyond people you know personally.

`sub`, `iat` and `exp` are all required on decode. A token without an expiry never expires,
so its absence is a rejection rather than a default.

**Delivery is a log line.** `send_link()` writes the URL to the log; swapping its body for
an HTTP call to a provider is the whole change at launch. No adapter, no interface, no
config with one value — an abstraction with one implementation is what CLAUDE.md forbids.

**`/auth/request` never reveals whether an address is known.** Same status and same body
either way. It is unauthenticated by definition, so a different answer for an unknown
email would be a user-enumeration oracle.

**What this closes.** 2.1 shipped `POST /events` with `user_id` as a query parameter and
nothing behind it: anyone could write events attributed to anyone. The user id now comes
from the bearer token and nowhere else, and a test asserts that naming a victim in the
query string is ignored.

**Known gap, not built.** `/auth/request` has no rate limit and is an email-send
amplifier. Harmless while delivery is a log line; it needs one before a real provider is
wired in. Recorded rather than half-built.

D2's deferred foreign key on `training_contexts.user_id` is also added here, since the
users table it was waiting for now exists.

## D24 — One default training context per user, enforced by the database — APPLIED

PRD §7 gives `training_contexts.is_default` with nothing saying only one may be set. Two
defaults is a bug — session start has to pick one — and "clear the old default before
setting the new one" is two statements that a crash in between leaves half-done, or that
two concurrent requests interleave.

A partial unique index on `(user_id) WHERE is_default` makes it unrepresentable. The
handler still demotes the previous default first, but the index is what guarantees it.

Two related rules the API keeps, neither of which the PRD states:

- **The first context a user creates is their default**, whatever the request said. A user
  holding contexts with no default has no session to start.
- **Deleting the default promotes another.** Same reason, from the other direction.

Uniqueness is per user, not global — two users each having a default is the normal case,
which is why the index is on `(user_id)` and not on `is_default` alone.

## D25 — Plans are stored whole, as one JSONB row — APPLIED

`plans(id, user_id, training_context_id, week_of, generated_at, engine_version, payload)`,
with the whole `Plan` in `payload`.

The plan is always read whole — the client needs every session and every substitution set
offline, because the occupied-machine swap happens mid-set in a basement with no signal
(§6) — and nothing queries inside it. Phase 3 analytics will read the event log, not the
plan. Normalising into plans/sessions/items/substitutes would be four tables and a join to
answer the only question anyone asks.

**The row is a cache, not a source of truth.** The engine is pure and deterministic, so
the same context and the same days produce the same plan. `engine_version` records which
engine produced it, which is what makes a replay through a new version comparable rather
than merely different.

One plan per user per week, enforced by a unique index on `(user_id, week_of)`.
Regenerating replaces rather than accumulating, for the same reason: the newest run of a
deterministic function is the answer.

`week_of` is the Monday of the week the first session falls in, in the user's own zone —
the API takes calendar dates the client has already resolved, since the engine has no
clock and "no muscle hard on consecutive days" (D14) needs real dates rather than a
session count. Monday/Wednesday/Friday and Monday/Tuesday/Wednesday are not the same week.

**Job ownership.** The caller is recorded in the RQ job's metadata and checked on every
poll. A job id is guessable enough that `GET /jobs/{id}` must not leak another user's
plan; like a context, someone else's job is 404 rather than 403.

## D26 — Shipped substitutes carry a name, not just an id — APPLIED

`PlanItem.substitutes` was a tuple of bare uuids. That is useless where it is actually
used: the occupied-machine swap happens mid-set in a basement with no signal (§6), and a
client cannot render "swap to X" for a uuid it has no name for. Looking the name up is
exactly the request §6 says will not succeed.

Each substitute now carries `exercise_id`, `slug` and `equipment` — enough to show the
option and what it needs, resolved at generation and shipped inside the plan.

This is what makes 2.5's occupied-equipment flow work offline, and it is verified that
way: an end-to-end test takes a real plan, goes offline, taps "in use", and asserts the
swap resolves locally with no request.

## D27 — Gym archetypes are seeded data, and the API serves them unauthenticated — APPLIED

`gym_archetypes` has existed since Phase 0 and had never held a row, which is also why
D12's reference to a `minimal_apartment` archetype dangled. Six presets now live in
`seeds/gym_archetypes.yaml`, loaded by the same converge-don't-append rule as equipment,
with every slug resolved through the alias table so a typo fails the seed rather than
quietly producing a thinner gym than the user has.

`GET /contexts/archetypes` is deliberately unauthenticated. It is catalog data, and
requiring a login before someone can see what the app supports is friction for nothing —
PRD §12 already names onboarding friction as a real cost. Presets are ordered leanest
first, because the launch cohort is the minimal-equipment user and they should not have to
scroll past a commercial gym to find their apartment.

Onboarding now picks an archetype rather than a hardcoded list, which is the "one question
instead of two hundred" §7 describes. Amendments stay a later, optional step.

## D28 — Training context is last-used with a one-tap switch — APPLIED

PRD §12 asks: prompt for the training context at session start, or infer it? It already
leans — "defaulting to last-used with a one-tap switch is probably right" — and this
settles it that way.

Asking every session is friction on the one screen that must be fast; the logger is used
mid-set, one-handed, and a question before the first tap is a question in the way.
Geofencing would infer it correctly and needs location permission this app has no other
use for, which is a bad trade for a cohort of eight.

The last-used id lives in `localStorage` on the client, not on the account. Which place
you are standing in is a property of the device in your hand, not of the user — a phone
and a laptop can honestly disagree about it, and the server has no way to know which is
right. `is_default` on the context stays what it was: the account-level fallback for a
device that has not chosen yet.

The switch appears on the plan screen only when there is more than one context, and
switching regenerates, because a plan built from the wrong rack is not worth showing.

## D29 — The profile is collected ahead of its consumers — APPLIED

PRD §12 asks how much onboarding friction is acceptable before the first plan. This
resolves it toward *more* questions, deliberately and against the cheaper option.

Intake now asks seven things. Four of them — goal, experience, sessions per week, session
length — are live engine inputs that `PlanRequest` has accepted since 2.2c and that the
client had been hardcoding to `hypertrophy`/`intermediate`/`3 days`/`60 minutes`. Those
are unambiguous wins: they cost four taps and they change the generated plan.

The other three — birth year, height, bodyweight — are **stored and read by nothing**.
No code in `engine/` references them. They are collected now so the profile exists when
the engine wants it, which is a real cost paid against an uncertain return, and it is
recorded here so a later reader does not mistake three unused columns for a bug.

Bodyweight is the one with a consumer already waiting: press-ups, pull-ups and dips carry
no load at all today, so `best_e1rm_estimate` and double progression silently do not
apply to them. Wiring it up is an engine change with property tests, not a UI change, and
it is the first thing that should happen to these columns.

Two things are deliberately *not* asked. **Sex** is omitted because the volume landmarks
(D11) are sex-neutral in this codebase, so nothing would consume it, and it is the most
sensitive field on the form; it is trivial to add when the landmarks become sex-aware.
**Goal weight and body composition** are omitted because this app prescribes training and
has no business pointing anyone at a number on a scale. The body-shape question is asked
as a training outcome — "get stronger" or "build muscle" — which is exactly the `Goal`
enum the engine already honours, and which is the most it can honestly promise.

Storage is metric and canonical; imperial is a display concern that never reaches the
server. Bodyweight is a single current value rather than a series — it is genuinely
time-varying and belongs in the event log the day something reads it over time, which is
the same day the calisthenics work lands.

## D30 — Household objects are equipment, and the generator says what it cannot reach — APPLIED

Asked what happens to a user with no equipment, the generator was run against an empty
equipment set. It returned a full 60-set plan whose largest single allocation was **six
sets of chin-ups**, and which contained **no chest work at all**. Nothing reported either.

CLAUDE.md's equipment-subset invariant passed throughout. It passed because the catalog
was wrong, not because the behaviour was right — an invariant checked against bad data is
worth nothing, which is the more general lesson.

**One root cause, two symptoms.** `ingest/taxonomy.py` mapped the source's `"body only"`
to no equipment. The source means "you lift your own bodyweight", not "no apparatus", so
`chin_up`, `pullups`, `v_bar_pullup`, `bench_dips` and `dips_triceps_version` all entered
the catalog claiming to need nothing. Two consequences, the second hidden by the first:

1. A user with an empty room was prescribed chin-ups, and `pull_up_bar` — listed in the
   `minimal_apartment` archetype since Phase 0 — was required by **no exercise at all**.
2. Those mislabelled dips occupied the bodyweight tier-0 slots for `horizontal_press`
   under `PER_PATTERN_CAP`, so the real push-ups lost their slot to them and sat in
   `review.csv`. Chest therefore had no bodyweight exercise on *any* context, including
   `minimal_apartment` — the archetype D12 names as the supported floor.

Fixing the first frees the slots and the ingest supplies push-ups on its own. Apparatus
rules now live beside `PATTERN_RULES` in the same keyword idiom, including one for the
incline and decline variants: elevating either end of a push-up needs something to elevate
onto, and without that rule the incline versions held the slots the flat push-up should.

`loadable` was corrected in the same pass: apparatus that only holds the body up does not
make a movement loadable, so a pull-up bar no more loads a pull-up than a bench loads a
push-up. `resistance_bands` is deliberately excluded from that set even though the seed
gives it no increments — whether bands are loadable is an open question in PRD §12 and
answering it here would resolve it silently.

**Household objects.** After the fix `vertical_pull` has no zero-equipment terminal, which
is what D12 said from the start: pulling requires something to pull on.
`seeds/exercise_terminals.yaml` had already named the answer in its own comments — *"an
inverted row under a table is the honest answer and needs the catalog to model a table"*.
So `chair`, `sturdy_table` and `dip_station` are equipment now. The first two cost nothing
and are in every home, and between them carry a genuine inverted row and genuine dips.
They sit in tier 1 beside the pull-up bar, not tier 3 with the barbells, and they hold the
body without loading it. A new `bodyweight_only` archetype carries the chair and table;
a genuinely bare room removes them, which is what `equipment_removed` is for.

**Saying so.** `Plan` gained an `unreachable` tuple: the muscles no exercise the context
can express will train. Raising was considered and rejected — a plan missing one muscle is
still worth training — but returning it silently is the failure this decision exists to
close. It is computed from the usable candidate set, so it means "your equipment cannot
express this" and never "the time budget ran out". Two property tests assert it is
*exactly* the set of muscles with no usable exercise, in both directions: a muscle missing
from it is the silent hole, and a muscle wrongly in it tells a user to buy something they
do not need.

Measured after the change: a bare room reports `forearms, lats, traps` and prescribes
nothing needing a bar; adding a chair and a table reduces that to `forearms, traps`;
`minimal_apartment` reduces it to `forearms` and prescribes chin-ups, correctly, because
that context owns a bar. Forearms and traps remain genuinely uncoverable without something
to grip or load, and the app now says so rather than quietly omitting them.

## D31 — Password sign-in alongside the magic link — APPLIED

Amends D23. Magic-link delivery is still a log line, so every sign-in meant reading a
token out of the server log. Until a mail provider is wired in, the app signs in with an
email and password; the magic-link endpoints stay, and stay tested, for when it is.

**Hashing is stdlib `hashlib.scrypt`**, salted per user, stored as
`scrypt$<salt>$<digest>` in a nullable `users.password_hash` (migration 0008). No
bcrypt/argon2 dependency: scrypt is memory-hard and already installed.

**Sessions are unchanged.** Signup and login issue the same stateless JWT as
`/auth/verify`, with the same 7-day lifetime and the same lack of revocation.

**Every failed login answers the same** — unknown address, magic-link-only account, wrong
password — and an unknown address is still checked against a decoy hash, so response time
does not tell them apart either.

**Signup refuses any taken address, with or without a password.** Setting a password on
someone else's magic-link account would be taking it over. The cost is that signup
reveals whether an address has an account (409); that is the normal trade for a sign-up
form, and the magic-link endpoint keeps its no-enumeration guarantee.

**Known gap, not built.** `/auth/login` has no rate limit or lockout, so it can be
brute-forced. Acceptable on a local stack; required before this is reachable from the
internet. Recorded rather than half-built, like D23's `/auth/request` gap.

## D32 — Exercise photos and steps from the catalog source; video is a link out — APPLIED

Amends the PRD §3 non-goal on form instruction. The non-goal exists because producing or
licensing technique content "is a full-time job that will consume this project". That
reason does not apply to content we already have: free-exercise-db, the Unlicense source
the catalog is ingested from (`ingest/fetch.py`), ships two photos per exercise (start and
end position) and numbered steps. Ingest used to drop both.

**Shown, not produced.** `ingest/media.py` copies the photos into `web/public/exercises/`
and writes `index.json` (slug → frames, steps). Bundled rather than hotlinked: served from
our origin, cached by the service worker, so they render in a gym with no signal. About
11 MB on disk, committed. Re-running ingest fetches only what is missing.

**Two frames cross-faded in a loop stand in for video.** Start and end position, alternated,
read as the movement. Under `prefers-reduced-motion` the first frame stands still.

**Video is a link out, never embedded.** "Watch how" opens a YouTube search for the
exercise. No curation, no embeds, no links to rot, and it is exactly the PRD's "link out
to existing references; don't build a library".

**Steps are behind a closed disclosure.** "What do I do" stays the product; "how" is one
tap away for whoever wants it.

**Hand-authored terminals borrow photos, never steps.** `image_from` in
`seeds/exercise_terminals.yaml` names a source exercise whose photos show the same
movement. Its written steps describe a different exercise (a walking lunge is not a
stationary one), so a borrowed entry has frames and no steps. Entries without a faithful
match (pike push-up, YTW, the self-resisted curl and raise) have no photo rather than a
misleading one.


## D33 — The default context moves only by promoting another — APPLIED

`PUT /contexts/{id}` with `is_default: false` on the current default used to demote it in
place, leaving a user with contexts and no default, the state `create` and `delete`
already refuse to produce. Now the flag is ignored in that one case: the context stays the
default, and the response says so. The default changes only when another context is made
the default, whether by `create` or by `PUT` with `is_default: true`. No 422, so a client
that round-trips GET → PUT with an edited label keeps working.
