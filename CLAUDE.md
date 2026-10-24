# CLAUDE.md

Project context for Claude Code. Read this before any task in this repo.

---

## What this is

Loadout — an adaptive training app. Generates strength training plans constrained by the equipment a user actually has access to, then adjusts prescriptions session-to-session based on logged performance.

Full spec: `docs/PRD.md`. Read the relevant section before implementing anything it covers. If your implementation would contradict the PRD, stop and say so rather than silently diverging.

Resolutions: `docs/decisions.md`. The PRD had gaps and self-contradictions; each is resolved there with an ID (D1–D16) and the PRD points at them inline. **Where the two conflict, decisions.md wins.**

**The two mechanisms that carry the product:**
1. A substitution graph — exercises as nodes sharing a movement pattern, edges for equipment downgrade, difficulty step, and lateral equivalence.
2. A progression engine — deterministic arithmetic over logged performance (Epley e1RM, double progression, volume landmarks).

---

## Architectural constraints — do not violate without asking

These are not preferences. Violating them requires a conversation first.

**1. Engine modules are pure functions.**
`generator/`, `progression/`, and `graph/` take state as arguments and return decisions. No database access, no HTTP calls, no clock reads, no randomness without an injected seed. If you need the current time, it is a parameter. This exists so we can replay a user's full history through a new engine version and diff the output. Any I/O inside these modules breaks that and is a bug.

**2. Events are append-only and never mutated.**
The `events` table is the source of truth. `UPDATE` and `DELETE` on it are forbidden. Anything that looks like current state is a projection, derived and rebuildable from the log. If a projection is wrong, we replay — we do not patch.

**3. Event IDs are generated on the client.**
Every event carries a client-generated UUID which is the idempotency key. `INSERT ... ON CONFLICT (id) DO NOTHING`. Retries must be free. Never let the server assign an event ID.

**4. The LLM never produces a training prescription.**
It parses free-text user feedback into a validated schema, and it narrates decisions the engine already made. It does not select loads, reps, sets, or deloads, and it does not override the fatigue gate. The boundary is prescriptions, not numerals — read it that way and don't over-apply it (D8). Confidence on parsed feedback is an enum because model confidence floats aren't calibrated, which is a separate reason. Every LLM call is async, schema-validated on return, and falls back to a deterministic template on failure. The app must pass its full test suite with LLM calls disabled via feature flag.

**5. Equipment belongs to a training context, not to a user.**
A user has many contexts (home, work gym, hotel) and selects one per session. Never add an equipment column to the users table.

**6. Timezones.**
Store UTC plus the user's IANA zone. Never store naive local time. "Did I train today" is computed in the user's zone.

---

## Stack

- Frontend: Next.js App Router, TypeScript strict, Tailwind
- Local persistence: IndexedDB via Dexie (the offline event queue)
- API: FastAPI, Pydantic v2, Python 3.12
- DB: PostgreSQL 16, migrations via Alembic
- Queue: Redis + RQ
- Tests: pytest + Hypothesis (Python), Vitest (TS)

**Do not introduce** without asking: Kafka, Neo4j, Kubernetes, a second database, GraphQL, an ORM other than SQLAlchemy Core, a state management library beyond TanStack Query, or any new service. This project is a modular monolith on purpose. Resume-driven architecture is a bug.

---

## Running locally

`make up` / `make down` / `make status` / `make logs`. `make seed` once on a fresh
database (catalog, graph, exercise media). `make test` for unit tests, `make e2e` against
a running stack. Ports come from `.env`; if 5433 is taken on a machine, change
`POSTGRES_PORT` there, not in the Makefile. Web on 3000, API (and `/docs`) on 8001.

## Code conventions

- Python: type hints on every function signature. `ruff` + `mypy --strict` on `engine/`.
- SQL: raw SQL in a `queries/` module. No ORM query builders for graph traversal — write the recursive CTE by hand and keep it readable.
- TypeScript: `strict: true`. API client types are generated from FastAPI's OpenAPI schema — never hand-write them.
- Errors: fail loudly in the engine. No silent defaults. A missing exercise should raise, not return an empty plan.
- No comments explaining *what* code does. Comments explain *why* a non-obvious decision was made.

---

## Testing requirements

Engine code requires property tests, not just examples. Use Hypothesis. The invariants that must hold for every generated plan:

- Load never increases by more than `max(10%, one available equipment increment)`, **and never by more than 20% under any circumstance** (D13). Assert both bounds separately — the second is not implied by the first. Sole exception: a state flagged `is_estimated` may correct past both bounds on its first logged session, once, in either direction (D15). Exempt exactly that transition and nothing else.
- Weekly hard sets per muscle group never exceed that muscle's MRV
- No muscle group is programmed hard on consecutive calendar days ("hard" = prescribed target RIR ≤ 3, per D7)
- Every prescribed exercise's equipment is a subset of the active training context's equipment
- Graph traversal terminates within depth 3 and never returns a node of a different movement pattern

A change to engine logic without a corresponding property test is incomplete.

---

## How to work with me

- **Small units.** One module or one migration per task. If a task looks like it needs more than ~300 lines, stop and propose a split.
- **Plan before writing.** For anything non-trivial, outline the approach and wait for confirmation. I would rather correct a plan than a codebase.
- **Ask when the PRD is ambiguous.** It has open questions in §12 that are genuinely unresolved. Do not resolve them silently by picking one.
- **Don't scaffold speculatively.** No abstract base classes for one implementation, no config for things that have one value, no `utils.py`. Build what the current task needs.
- **Say when something is a bad idea.** If I ask for something that contradicts the constraints above, push back rather than complying.

## Current phase

**Phase 2 is built and blocked on its exit criteria, not on more code.** PRD §10 sets
those at 8 users and 2 weeks of real logs. Phases 2.5, 3, 4 and 5 are gated behind that
by `build-prompts.md`, and Phase 3 in particular is meaningless against synthetic data.

Built and verified:

- **Phase 0** — catalog (89 exercises), equipment taxonomy, substitution graph (216 edges,
  every movement pattern reaching a zero-equipment terminal)
- **Phase 1** — progression primitives, double progression, volume landmarks, fatigue
  gate, plan generator. `engine/` is pure throughout and property-tested, including 1000
  generated plans against every invariant above.
- **Phase 2** — append-only event log with projections, magic-link auth, contexts CRUD,
  RQ plan generation, and a Next.js PWA with an offline-first IndexedDB queue.
- **Phase 2.5** — gym archetypes, occupied-equipment swap flow
- **Product UI** — design tokens, component set, responsive shell, intake, settings.
  Closes the gaps where the API supported something the UI never exposed: switching
  training context (constraint 5), the four generator inputs the client hardcoded, and
  `workout_completed` / `workout_abandoned`, which were defined and never emitted.
- **Redesign** — bold athletic visual system (volt accent, Barlow Condensed display
  face). Today / Week / Progress / Settings replace Plan and History; a full-screen
  `/workout` replaces the per-exercise logger; `/summary` closes a session. Old routes
  redirect. Client e1RM (Epley) is display only — PRs and trends, never prescriptions.

D1–D32 in `docs/decisions.md` are settled.

Every stated acceptance criterion is verified, 2.3's offline session included — both
Playwright specs drive a real browser against a running stack.
