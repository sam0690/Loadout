# Adaptive Home Training — Product & Technical Design

**Status:** Draft v1
**Owner:** [you]
**Last updated:** 2026-08-29
**Resolutions:** `docs/decisions.md` — gaps and contradictions in this document are resolved there (D1–D16, all settled). Where they conflict, decisions.md wins.

---

## 1. Problem

People fail to train consistently for two reasons that look different but are the same problem: they don't know what to do with the equipment in front of them, and they follow a static plan that stops fitting them by week three.

At home, "the equipment in front of them" is a pull-up bar and one adjustable dumbbell. Existing apps assume a gym, so home users get a plan full of barbell movements they can't perform, and the swap flow dumps them into an unfiltered catalog and asks them to be their own coach.

At the gym, the same person is surrounded by 200 machines and has no idea which ones matter, in what order, or what to do when the bench is occupied. The constraint inverted — too much equipment instead of too little — but the failure is identical: no mapping from *what's available right now* to *what I should do next*.

That mapping is the product. The substitution graph handles both directions.

## 2. What we're building

A system that generates a training plan from the user's actual constraints — equipment on hand, time per session, experience, injuries — and then adjusts it every session based on logged performance.

Two mechanisms carry the whole product:

**The substitution graph.** Exercises are nodes sharing a movement pattern, connected by edges that represent equipment downgrade and difficulty adjustment. When the ideal exercise isn't available, the generator walks the graph until it lands on something the user can actually do.

The graph is context-agnostic, which is why gym support is nearly free. A home user starts partway down and walks further down. A gym user starts at the top and doesn't walk at all — until a machine is occupied, at which point they walk sideways to an equivalent. Same traversal, three different triggers:

- `unavailable_owned` — user doesn't own it (home)
- `unavailable_here` — this gym doesn't have it (gym archetype gap)
- `unavailable_now` — someone else is using it (mid-session, gym)

**The progression engine.** After each session, per-exercise state advances or regresses based on logged reps and RIR. Deterministic, not learned.

## 3. Non-goals

Explicitly out of scope for v1. Each of these is a real product; none of them is this product.

- Nutrition, calorie tracking, macros
- Social features, feeds, sharing, leaderboards
- Wearable integration (HRV, heart rate, sleep)
- Cardio and conditioning programming
- Coaching marketplace or human trainers
- Anything resembling medical or rehab advice
- **Form instruction, technique video, or machine setup guidance.** This deserves its own line because gym scope makes it tempting. "I don't know *how* to do it" is a real and serious gap — arguably the one that makes gym beginners quit — but it is a content production problem, not an engineering one. Producing or licensing 200 technique videos is a full-time job that will consume this project. We solve "what do I do," not "how do I do it," and we say so plainly in the UI. Link out to existing references; don't build a library.
- **Exhaustive per-gym equipment inventories.** We use archetypes (§7.4). We will not build a crowdsourced database of what's in every gym on earth.

## 4. Users

**Primary (launch cohort):** trains at home, owns some subset of {nothing, bands, adjustable dumbbells, pull-up bar, bench, kettlebell}, 3–5 sessions/week, 30–60 min, wants muscle and strength, not a beginner but not a competitor.

**Secondary (phase 2.5):** trains at a commercial gym, has access to far more than they use, defaults to the same four machines every session because choosing is exhausting. Same person as above, different constraint.

**Also served, free of charge:** the user who is *both*, gym on weekdays and home on weekends. Because equipment is modeled as a per-session context rather than a per-user property, this works without special-casing — and it's a genuinely common pattern that most apps handle badly.

**Explicit anti-user:** the competitive powerlifter. That's Juggernaut's market and it demands peaking blocks, attempt selection, and meet prep. Serving them well would double the scope.

---

## 5. Tech stack

Chosen for boring reliability plus a few deliberate stretches. Every non-obvious choice has a rationale, because "why did you pick X" is the question you'll be asked.

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js (App Router), TypeScript, Tailwind | You already know it. Server components cut client JS on the plan view. PWA-capable for the offline path. |
| State/sync | TanStack Query + IndexedDB (Dexie) | IndexedDB is the local event queue. Retrofitting this later is a rewrite; scaffold it in week one. |
| API | FastAPI (Python) | Puts the progression engine in the same language as the pipeline. Pydantic gives you typed contracts, OpenAPI gives you a generated TS client for free. |
| Database | PostgreSQL 16 | Recursive CTEs for graph traversal, JSONB for the event payloads, partial indexes for the hot queries. One database. |
| Cache/queue | Redis + RQ | Plan generation is async. RQ over Celery because Celery's config surface is larger than this project needs. |
| Analytics | dbt + Postgres (later: DuckDB) | Do not stand up Snowflake for eight users. dbt against your own Postgres teaches the same modeling discipline. |
| Orchestration | Cron → Dagster (phase 3) | Cron is fine until you have DAG dependencies. Adopt Dagster when you feel the pain, not before. |
| LLM | Anthropic API, structured outputs | Narrow role. See §9. |
| Hosting | Fly.io or Railway, Neon for Postgres | Cheap, fast to deploy, no Kubernetes. |
| Observability | Sentry + structured JSON logs | Add OpenTelemetry when you have services worth tracing. |

**Deliberately rejected:** Neo4j (Postgres handles a few thousand nodes fine), Kafka (you will not have the throughput), microservices (a modular monolith is the correct architecture at this size), Kubernetes (nothing here needs it). Being able to explain *why you didn't* reach for these is worth more than having used them.

---

## 6. Architecture

```
┌──────────────────────────────────────────────────┐
│  Next.js PWA                                     │
│  plan view · logger · history                    │
│  IndexedDB event queue (offline writes)          │
└────────────────┬─────────────────────────────────┘
                 │ REST, OpenAPI-typed client
┌────────────────▼─────────────────────────────────┐
│  FastAPI                                         │
│  ┌────────────┬────────────┬──────────────────┐  │
│  │ Catalog    │ Generator  │ Progression      │  │
│  │ graph walk │ constraint │ e1RM, RIR rules  │  │
│  │            │ solver     │ (pure functions) │  │
│  └────────────┴────────────┴──────────────────┘  │
│  ┌────────────────────────────────────────────┐  │
│  │ Event ingest — append-only, idempotent     │  │
│  └────────────────────────────────────────────┘  │
└────────┬──────────────────────┬──────────────────┘
         │                      │
   ┌─────▼──────┐        ┌──────▼─────┐
   │ Postgres   │        │ Redis + RQ │
   │ catalog    │        │ plan gen   │
   │ events     │        │ LLM calls  │
   │ projections│        └────────────┘
   └─────┬──────┘
         │ nightly
   ┌─────▼──────────────────────────┐
   │ dbt: staging → marts           │
   │ swap rates, adherence, e1RM    │
   │ feeds back into generator      │
   └────────────────────────────────┘
```

The three engine modules are **pure functions with no I/O**. They take state, return decisions. This is the single most important structural decision in the codebase: it makes the interesting logic exhaustively testable without a database, and it means you can replay a user's entire history through a new version of the engine to see what would have changed.

### Request flow: generating a plan

1. `POST /plans` → validate constraints, enqueue job, return `202` with job id
2. Worker: load catalog, run solver, walk substitution graph for unavailable equipment, persist plan
3. Client polls `GET /jobs/{id}` (websockets are not worth it at this scale)

### Request flow: equipment occupied mid-session

The gym-specific flow, and the one worth demoing. User taps "in use" on the prescribed exercise.

1. Client already holds the session's exercise list *and* a precomputed substitution set for each — fetched with the plan, so this works with no network
2. Walk `lateral_equivalent` edges first, filtered to the active `training_context`
3. If no lateral match, walk `equipment_downgrade` and adjust the prescription for the difficulty delta
4. Emit `exercise_swapped` with `reason: 'unavailable_now'`
5. Seed the substitute's progression state from the source exercise, adjusted by the edge delta, and flag it `is_estimated` — the user should not lose their place because someone else was on the bench. Progression state is per-exercise and is **never** shared across a swap: a chest press machine and a dumbbell press are not the same strength. The seed is a guess, the flag says so, and the first logged session overwrites it (D15)

Step 1 is the design constraint that matters: substitutions must be resolved at plan generation and shipped to the client, not fetched on demand. Gym basements have no signal and this interaction happens mid-set.

The `reason` field on the swap event is worth calling out. `unavailable_now` means the gym is busy. `unavailable_owned` means our equipment model is wrong. A bare user-initiated swap means the user dislikes the exercise. Three completely different signals that would be indistinguishable if we logged a single `swapped` event, and only the third should influence exercise scoring.

### Request flow: logging a set

1. Client writes event to IndexedDB immediately, renders optimistically
2. Background sync `POST /events` with client-generated UUID
3. Server upserts on that UUID — replays are free, so retries are safe
4. Progression engine recomputes the exercise's next prescription synchronously (it's microseconds of arithmetic)

---

## 7. Data model

### Catalog

```sql
exercises (
  id uuid pk,
  slug text unique,
  name text,
  movement_pattern text,      -- closed set of 15, see D3
  primary_muscles text[],
  secondary_muscles text[],
  equipment text[],           -- canonical equipment.slug values, never free
                              -- text; empty array = bodyweight. See D1.
  difficulty smallint,        -- 1-10, within its pattern
  unilateral boolean,
  loadable boolean            -- can you add weight, or only reps/leverage?
)

exercise_edges (
  from_id uuid, to_id uuid,
  edge_type text,             -- 'equipment_downgrade' | 'difficulty_step'
                              -- | 'lateral_equivalent'  (same pattern, same
                              --   difficulty, different equipment)
  delta smallint,             -- difficulty(to) - difficulty(from), signed.
                              -- 0 for lateral by definition. See D6.
  primary key (from_id, to_id, edge_type)
)
```

`lateral_equivalent` is the edge that makes the occupied-machine flow work: cable row and chest-supported row are the same movement at the same difficulty, so you swap without disturbing the progression state. Home users rarely traverse it; gym users hit it constantly.

Traversal is a recursive CTE bounded to depth 3. Candidates rank by fewest hops, then smallest absolute cumulative delta, then slug — the last key exists so replay is deterministic (D6). Seed roughly 80 well-modeled exercises, not 800 badly-tagged ones.

### Equipment taxonomy

The change that must happen before any gym ingest. Equipment is currently a `text[]` of free strings, which is survivable for eight home items and catastrophic for machines — a Hammer Strength Iso-Lateral Row and a Life Fitness Pulldown are brand names, not categories, and left as free text they fragment the catalog into hundreds of near-duplicates.

```sql
equipment (
  id uuid pk,
  slug text unique,           -- 'cable_stack', 'seated_row_machine'
  class text,                 -- 'free_weight' | 'machine' | 'bodyweight'
                              -- | 'band' | 'bench' | 'bar'
  movement_patterns text[],   -- what this can be used for
  is_fixed_path boolean       -- machines constrain the movement path;
                              -- affects difficulty and injury substitution
)

equipment_aliases (
  equipment_id uuid,
  alias text,                 -- 'Hammer Strength Iso-Lateral Row'
  source text,                -- brand, region, or ingest source
  primary key (equipment_id, alias)
)
```

Canonical rows, brand names as aliases. Ingest resolves through the alias table or fails loudly rather than creating a new row.

### Gym archetypes

You cannot ask a user to enumerate 200 machines. You ask them one question.

```sql
gym_archetypes (
  id uuid pk,
  slug text,                  -- 'commercial_chain' | 'hotel' | 'university_rec'
                              -- | 'garage' | 'crossfit_box' | 'minimal_apartment'
  name text,
  equipment_ids uuid[]        -- the preset
)

training_contexts (
  id uuid pk,
  user_id uuid,
  label text,                 -- "home", "work gym", "my parents' place"
  archetype_id uuid null,     -- seed, nullable for pure custom
  equipment_added uuid[],     -- user amendments to the preset
  equipment_removed uuid[],
  is_default boolean
)
```

Resolved equipment is `(archetype preset | equipment_added) - equipment_removed`, removal applied last (D10). `user_id` carries no foreign key until auth lands in Phase 2 (D2).

Note the shape: **equipment belongs to a context, not to a user.** A user has many contexts and picks one at session start. This is what makes the gym-plus-home user work without special-casing, and it's the reason this table needs to exist in Phase 0 even though gyms don't launch until 2.5. Adding it later means migrating every existing user's inventory.

Archetype presets cover perhaps 80% of what's actually present. The amendment arrays absorb the rest, and aggregate amendment patterns eventually tell you how to improve the presets — another thing the event pipeline gets for free.

### Events (append-only, the source of truth)

```sql
events (
  id uuid pk,                 -- CLIENT-generated, this is the idempotency key
  user_id uuid,
  type text,                  -- set_logged | exercise_swapped | workout_completed
                              -- | workout_abandoned | feedback_submitted
  payload jsonb,
  client_ts timestamptz,      -- when it happened
  server_ts timestamptz,      -- when we heard about it
  user_tz text                -- IANA. "did I train today" is a hard question
)
```

Never mutate. Never delete. Current state is a projection.

### Projections (derived, rebuildable)

```sql
exercise_state (
  user_id uuid, exercise_id uuid,
  current_load numeric, current_reps smallint,
  e1rm numeric,
  consecutive_successes smallint,
  consecutive_failures smallint,
  is_estimated boolean,       -- seeded across a graph edge, not yet logged
                              -- against. While true, the next session may
                              -- correct load past the D13 bounds, once. See D15.
  last_performed_at timestamptz,
  primary key (user_id, exercise_id)
)
```

If a projection is ever wrong, drop it and replay the event log. That property is worth a lot.

---

## 8. The progression engine

This is the "AI" in every competing product. It is arithmetic.

### Estimated 1RM

Epley: `e1RM = weight × (1 + reps / 30)`. Accurate to roughly 3% in the 2–10 rep range; degrades above 10 reps and for sets stopped well short of failure. Cross-check against the RIR→%1RM table (D5 — indexed by `reps + rir`, raises above 15) and take the higher value. e1RM trend over time is your primary progress signal.

### Double progression

Per exercise, hold load constant and add reps until the top of the range, then add load and drop to the bottom.

```
target = (load, rep_range)  e.g. (20kg, 8-12)

hit top of range at RIR >= 1  → if next increment <= 20% of current load:
                                    increase load, reset to bottom of range
                                  else: hold load, add reps past range top
hit top of range at RIR = 0   → hold load, repeat
below bottom of range         → count failure
2 consecutive failures        → deload load by 10%
```

Load increase is bounded twice and both bounds are asserted separately (D13):
never more than `max(10%, one available equipment increment)`, and never more
than 20% under any circumstance. The second is not implied by the first — a
rack that jumps 10kg to 30kg satisfies "one increment" with a 200% increase.

The single exception is a state flagged `is_estimated`: a seeded node has never
been trained against, so its first logged session may correct load past both
bounds, once, in either direction (D15).

For bodyweight movements where `loadable = false`, "increase load" means walking a `difficulty_step` edge in the graph instead. That's the substitution graph earning its keep a second time.

### Volume landmarks

Track weekly hard sets per muscle group against MEV / MAV / MRV. Only sets at RIR 0–3 count. Compounds credit their primary muscle; avoid double-counting into secondaries. Start from published defaults, adjust per user based on their recovery signals.

```
volume < MEV   → add a set next week
MEV ≤ v ≤ MAV  → progress normally
v approaching MRV → hold
4-6 weeks accumulating → deload to MEV for one week
```

Landmark values per muscle group are in D11. "Hard set" has two definitions and they are not interchangeable (D7): the generator asserts its invariants against **prescribed** hard sets, meaning target RIR ≤ 3, because it cannot know what the user will actually hit. Projections count **logged** hard sets at actual RIR 0–3.

The per-exercise deload and the weekly volume deload run at different levels and do not reset each other (D9).

### Fatigue gate

Before prescribing, check: was this muscle group trained hard on the previous calendar day in the user's IANA zone? Day-granular, not hour-granular — a plan assigns sessions to days, so an hours-based threshold is false precision over a decision never made at that resolution (D14). Is the user reporting elevated soreness? Did they abandon the last session? Any of these caps the prescription regardless of what progression says.

**All of the above is pure functions over `exercise_state` plus recent events.** Property tests should assert the invariants: load never increases more than 10% session-over-session, volume never exceeds MRV, no muscle group is programmed hard on consecutive days.

---

## 9. Where the LLM goes

Two jobs. Both at the edges. Neither touches a number.

### Job 1 — parse unstructured feedback

Input: `"left shoulder felt a bit tweaky on the last two sets of press"`

Output (structured, schema-validated):
```json
{
  "affected_area": "left_shoulder",
  "severity": "mild",
  "movement_patterns_implicated": ["vertical_press", "horizontal_press"],
  "recommended_action": "substitute",
  "confidence": "high"
}
```

That structured object then goes into the **deterministic** engine, which decides what actually happens. The LLM converts language to signal. The rules decide.

### Job 2 — explain the change

Input: the diff the engine already produced. Output: a sentence a human wants to read. "Your bench e1RM has been flat for three weeks while volume climbed, so I've dropped a set and added load." The decision is already made; the LLM narrates it.

### Hard boundaries

The LLM **never**:
- selects loads, reps, or sets
- decides deloads
- overrides the fatigue gate
- sees anything a user typed without treating it as untrusted input

The boundary is **training prescriptions**, not numerals in general. `confidence`
is an enum rather than a float because self-reported model confidence is not
calibrated — 0.8 does not mean 80% — not because a decimal would breach the
boundary (D8). Do not over-apply this to things like a count of implicated
movement patterns.

Every LLM call is async (queued, not in the request path), schema-validated on return, and falls back to a deterministic template on failure or timeout. The app must work correctly with the LLM entirely switched off. Build it that way and prove it with a feature flag.

**Safety note:** any output that could read as medical advice gets templated, never generated. Pain is not a programming problem.

---

## 10. Phasing

| Phase | Scope | Weeks | Exit criteria |
|---|---|---|---|
| 0 | Catalog ingest, taxonomy normalization, 80-node substitution graph | 2–3 | Every pattern reaches a terminal within the `minimal_apartment` archetype; unreachable sets raise rather than return empty (D12) |
| 1 | Constraint solver + progression engine, pure, tested | 3–4 | Property tests pass on 1000 generated plans |
| 2 | Auth, plan view, logger, swap. Ship to 8 real people, **home only** | 4–6 | 8 users, 2 weeks of real logs |
| 2.5 | Gym archetypes, machine catalog ingest, occupied-equipment flow | 2–3 | Gym user gets a valid plan; swap resolves offline |
| 3 | Event pipeline, dbt marts, swap-rate feedback into scoring | ongoing | Generator measurably improves from real data |
| 4 | React Native, offline sync, conflict resolution | 4–6 | Full session loggable in airplane mode |
| 5 | LLM feedback parsing + explanation | 2–3 | Feature-flag off changes nothing functional |

Phase 3 is blocked on Phase 2 producing real events. Seeding synthetic data teaches the tooling and none of the judgment.

**Why gym support is modeled in Phase 0 but launched at 2.5.** The schema cost of supporting gyms is near zero *now* and expensive later — `training_contexts` in particular means migrating every user's inventory if deferred. But launching to both audiences at once splits an eight-person cohort into two groups of four, and four data points tell you nothing conclusive about either. Home-only launch also keeps the differentiation sharp: against Fitbod, the minimal-equipment case is where the substitution graph is the entire product rather than a convenience. Build the capability, hold the launch.

---

## 11. Success metrics

Product: week-4 retention, sessions completed per week per active user, swap rate per prescribed exercise (falling swap rate = generator improving).

Engineering: p95 plan generation under 3s, zero duplicate events under retry, projection rebuild from full event log under 60s.

## 12. Open questions

- Weekly plan regeneration vs. rolling next-session generation? Rolling adapts faster; weekly is more legible to the user. **Weekly for Phase 1 (D16) — a scope decision, not a permanent one. Still open beyond Phase 1; revisit when Phase 3 shows how often a generated week survives the week.**
- Do we model bands as loadable? Their force curve isn't linear and e1RM math doesn't apply cleanly.
- How much onboarding friction is acceptable before the first plan? Every question improves generation and costs conversion.
- Multi-user households sharing one equipment inventory — v2 or never?
- ~~Do fixed-path machines and free weights share progression state?~~ **Closed by D15: never shared, seeded across the edge and flagged `is_estimated`.** The `is_fixed_path` multiplier ships at 1.0 and still needs Phase 3 data. Original framing: A user who moves from dumbbell press to a chest press machine is not the same strength on both, so carrying e1RM across is wrong — but forcing a full recalibration every swap is worse UX. Possibly a per-equipment-class multiplier, possibly separate state with a seeded estimate.
- Do we prompt for training context at session start, or infer it? Asking every session is friction; geofencing is invasive and needs permissions we'd rather not request. Defaulting to last-used with a one-tap switch is probably right.
- Should archetype amendment data feed back into the presets automatically, or stay a manual curation step? Automatic risks one user's mislabeling propagating.
