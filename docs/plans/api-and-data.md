# API and data

The API is a FastAPI app in `src/hive/api/` (extra `api`). It owns persistence, the agent
worker pool and the photo pipeline, and serves the built frontend. The engine stays
stateless per request: load the game's moves from Postgres, replay them with
`GameRecord.replay()`, answer, and store any new move.

## Stack

| Concern | Choice | Notes |
|---|---|---|
| Web framework | FastAPI + uvicorn | Async throughout (see "Code structure"). Pydantic v2 request/response models in `api/schemas.py`, separate from DB models. |
| Settings | pydantic-settings | Env vars prefixed `HIVE_` or a `.env` file: database URL, S3 endpoint/keys/bucket, model name/version, pool size, budgets. Connection settings have no defaults; `make dev` copies `.env.example` (matching the compose stack) to `.env`. |
| Database | SQLAlchemy 2.x typed ORM (`Mapped[...]`) with its asyncio extension, psycopg 3, Alembic | No SQLModel. The same `postgresql+psycopg://` URL serves the async app and sync Alembic (run through `AsyncConnection.run_sync`). Relationships are `lazy="raise"` and loaded with `selectinload`. Migrations in `src/hive/api/db/migrations/`. |
| Object storage | Garage via `boto3` (S3 API) | A small async `ObjectStore` class (`put`, `get`, `delete_prefix`, `list_keys`, `check`) that runs boto3 calls in worker threads. Tests use `moto`'s in-process S3. |
| Logging | stdlib `logging`, `python-json-logger`, `asgi-correlation-id` | JSON lines with the `X-Request-ID` request ID; a pure ASGI access log middleware (route, status, latency). No `BaseHTTPMiddleware`, which breaks streaming. No `print` (`T20`). |
| Metrics | `prometheus-client` | `/metrics` endpoint. |
| Local dev | `deploy/compose.yaml` with Postgres and single-node Garage | `make dev` starts compose, migrates, and runs `hive serve --reload` (plus `vite` from WP 13). Garage bootstraps itself with `server --single-node --default-bucket` (v2.3+), creating the layout, the `hive` bucket and a fixed dev key, which `.env.example` matches. |
| Tests | pytest with the `anyio` plugin; `httpx2.AsyncClient` over `ASGITransport`; `moto` for S3; testcontainers Postgres | Async tests (`pytestmark = pytest.mark.anyio`) share one event loop per session (`anyio_backend` is session-scoped), so the async engine outlives single tests. No SQLite, so JSONB and Postgres behaviour are tested for real. A session-scoped container is migrated from scratch; each test runs in a rolled-back transaction. Without Docker the database tests skip locally (never in CI), or run against `HIVE_TEST_DATABASE_URL`, whose schema they drop and recreate. |

## Code structure (WP 10)

- **Routes** (`api/routes/`) are thin `async def` handlers: parse the request, call a
  service method, build the response model. Every resource router carries the full
  `API_PREFIX` (`/api`) itself, since FastAPI keeps route paths relative to the defining
  router and logs and metrics label requests by that path.
- **Services** (`api/games.py`, `GameService`) hold the behaviour on stored games. Each
  method that writes commits before it returns, so a call is one unit of work. WP 11 (moves,
  undo, state) and WP 12 (committing agent decisions) extend the service rather than the
  routes.
- **Errors** (`api/errors.py`): services raise `ApiError` subclasses (`GameNotFoundError`,
  later for example `PlyConflictError`), which one exception handler turns into an
  `ErrorResponse` (`{code, detail}`) with the error's status code. Routes declare them with
  `ApiError.openapi_responses(...)`, so the generated client knows every error shape.
- **OpenAPI**: operation IDs are the handler names (`create_game`, `list_games`), so they
  must be unique and stable; every response, including `/readyz` and the export download,
  has a schema.
- **Dependencies** (`api/dependencies.py`) are `async` (sync ones run in a worker thread).
  `SessionDependency` is scoped to the handler function, so the session is closed before
  the response is sent.
- **Async**: database and storage calls never block the event loop, which also carries
  the thinking streams and, in WP 12, the worker pool, so shared state like the pool needs
  only `anyio` primitives, no thread locks.

## Schema (WP 10)

```
game
  id            uuid pk
  name          text
  status        text      -- active | finished | abandoned
  rules         jsonb     -- serialized Rules
  setup         jsonb     -- "initial" or serialized BoardSetup from the editor
  white_player  jsonb     -- {"type": "human"} or {"type": "agent", "spec": AgentSpec, "budget_s": 5.0}
  black_player  jsonb
  result        text null -- white | black | draw
  created_at    timestamptz
  updated_at    timestamptz

move
  game_id       uuid fk → game (on delete cascade)
  ply           int       -- pk (game_id, ply)
  move          jsonb     -- serialized Move or null (pass)
  source        text      -- manual | photo | agent
  photo_id      uuid null fk → photo
  decision      jsonb null -- DecisionRecord for agent moves
  created_at    timestamptz

photo
  id            uuid pk
  game_id       uuid fk → game (on delete cascade)
  ply           int       -- the ply the photo was taken for
  object_key    text      -- Garage key: photos/<game_id>/<photo_id>.jpg
  width, height int
  reader        text null -- classical | yolo
  model_version text null
  detections    jsonb null -- raw TileObservations
  match         jsonb null -- top candidates with scores
  confirmed     bool      -- true once the move it proposed was committed
  created_at    timestamptz
```

All photos are kept, including unconfirmed ones, so a labeling pipeline can be added later
without schema changes. Deleting a game deletes its photo objects in Garage.

## Endpoints

All under `/api`. Request and response models are documented in OpenAPI and consumed by
the generated frontend client.

| Method | Path | WP | Purpose |
|---|---|---|---|
| GET | `/agents` | 10 | Agent kinds, descriptions and param schemas (from the factory registry). |
| POST | `/games` | 10 | Create a game: name, players, optional rules and setup. Rejects human vs human. |
| GET | `/games` | 10 | List games (filter by status, newest first, paginated). |
| GET | `/games/{id}` | 10 | Game metadata and move list. |
| PATCH | `/games/{id}` | 10 | Rename, change status. |
| DELETE | `/games/{id}` | 10 | Delete game, moves, photos (including objects). |
| GET | `/games/{id}/export` | 10 | Serialized `GameRecord` as JSON download. |
| GET | `/games/{id}/state?ply=N` | 11 | Board (stacks), hands, side to move, ply, result, last move, movable pieces, placeable coords and piece types. `ply` enables replay. |
| GET | `/games/{id}/targets?q=&r=` | 11 | Legal targets for the tile at `(q, r)`. |
| POST | `/games/{id}/moves` | 11 | Play a move: `{move, source, photo_id?, expected_ply}`. Validated with `Rules.apply_checked_move`; `expected_ply` gives optimistic concurrency (409 on mismatch). Updates status/result when the game ends. |
| DELETE | `/games/{id}/moves/last` | 11 | Undo the last move. |
| POST | `/games/{id}/think` | 12 | SSE stream. Body: `{agent?: AgentSpec, budget_s?, commit: bool}`. Streams `info` and `candidate` events, ends with `decision`. With `commit=true` (only allowed on an agent side, using that side's spec), the final move is stored with `source=agent` and its `DecisionRecord`. |
| POST | `/games/{id}/photos` | 16 | Upload a photo (multipart) for the current ply; stores it. From WP 19 also runs reader + matcher and returns candidates. |
| GET | `/photos/{id}/image` | 16 | Stream the stored image. |
| GET | `/healthz`, `/readyz` | 10 | Liveness; readiness checks DB, S3 and (from WP 24) model loaded. |
| GET | `/metrics` | 12 | Prometheus metrics. |

Static files: the built frontend (`frontend/dist`) is mounted at `/` with an SPA fallback
to `index.html` for client-side routes.

## Agent worker pool (WP 12)

- The pool holds persistent workers keyed by `(AgentSpec, Rules)`, up to `HIVE_POOL_SIZE`
  workers, evicting the least recently used idle worker when full. Workers are created
  lazily and reused across requests and games (`reset()` between games).
- A `think` request borrows a worker, runs one timed decision through the match runner's
  decision API, and streams the worker's messages to the client as SSE events. If the
  client disconnects, the decision is cancelled (stop event) and the worker returns to the
  pool after `IdleMessage`.
- Budgets are clamped to `HIVE_MAX_BUDGET_S`. Requests for a busy pool wait with a timeout
  and then fail with 503.
- The pool is shut down cleanly on app shutdown (lifespan handler). `hive serve` closes
  open streams after a 5 s graceful shutdown timeout, so `--reload` is never stuck on one.

### Streaming pattern (checked in WP 10)

- Use FastAPI's built-in SSE: `response_class=EventSourceResponse` on a path operation that
  `yield`s events (`fastapi.sse`), so no `sse-starlette`. Event models become part of the
  OpenAPI schema.
- A streaming route takes `DatabaseDependency`, not `SessionDependency`: function-scoped
  dependencies are closed while the generator still runs (an `IllegalStateChangeError`).
  Open short sessions with `database.session()`: one to load the game before streaming,
  one to commit the decision at the end. No connection is held during the stream.
- `AgentWorker.decide` blocks on pipes, so it runs in `anyio.to_thread.run_sync` with a
  `CapacityLimiter` sized to the pool (not the default limiter shared with other blocking
  calls). Its `message_callback` forwards messages into an `anyio` memory object stream
  with `anyio.from_thread.run_sync`, which the route reads and yields as events.
- A client disconnect cancels the route; the cancellation sets the stop event and the worker
  returns to the pool after `IdleMessage`.

## Observability (WP 12)

- JSON logs with request ID, game ID, route, latency; one log line per decision with the
  `DecisionRecord` fields; one per photo match (reader, latency, top score, margin).
- Metrics: HTTP request histograms by route and status, the decision metrics listed in
  `agents-and-matches.md`, pool gauges, `hive_photo_read_seconds{reader}`,
  `hive_photo_match_total{outcome}` (auto, candidates, failed).
- A `ServiceMonitor` scrapes `/metrics` in the cluster (WP 26).
