# Backend structure

`api/` is layered. A request goes in at the top, and each layer may only call the layers below it.

| Layer | Owns | Must not |
|---|---|---|
| `main.py` | `create_app()`: logging, CORS, error handlers, routers (order = OpenAPI path order) | hold routes or logic |
| `routers/` | HTTP only: path, status code, dependencies, calling one service function | contain SQL, import `sqlalchemy`, `schema` or `repositories` |
| `deps.py` | shared `Depends()`: `Db`, `RQ`, `Now`, `CurrentUser` | — it is HTTP, so it may raise `HTTPException` |
| `schemas/` | Pydantic request/response models, one file per domain | import `fastapi`, `sqlalchemy`, services, repositories or routers |
| `services/` | rules and transaction boundaries; the clock arrives as `now` | import `fastapi` or name a status code |
| `repositories/` | SQLAlchemy Core statements over a `sa.Connection` | decide anything, or open a transaction |
| `core/config.py` | everything `api/` reads from the environment (on top of `db.py`) | — |
| `core/security.py` | hashing and JWT arithmetic, with no HTTP types | import `fastapi` |
| `core/errors.py` | `NotFound`/`Unauthorized`/`Conflict`/`Invalid`, and their mapping to status codes | — |

`tests/test_layering.py` enforces the import rules.

Rules carried over from CLAUDE.md:

- Services call `engine/` and pass state in. The engine never imports anything here.
- `repositories/events.py` only appends (`ON CONFLICT (id) DO NOTHING`), with no UPDATE or DELETE.
  Event ids come from the client.
- Raw `.sql` that the worker also uses lives in top-level `queries/`. Repositories read it from there.
- A service signals failure by raising a `core/errors.py` class. The handler turns it into
  `{"detail": ...}` with the matching status, the same body `HTTPException` produces.

Changing a route's function name, a docstring, or a model's class name or docstring changes
`openapi.json`, which the web client is generated from. Run `scripts/dump_openapi.py` and diff it.
