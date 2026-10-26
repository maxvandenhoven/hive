# API and data

The API is a FastAPI app in `src/hive/api/` (extra `api`). It owns persistence, the agent
worker pool and the photo pipeline, and serves the built frontend. The engine stays
stateless per request: load the game's moves from Postgres, replay them with
`GameRecord.replay()`, answer, and store any new move.

## Stack

| Concern | Choice | Notes |
|---|---|---|
| Web framework | FastAPI + uvicorn | Async throughout (see "Code structure"). Pydantic v2 request/response models in `api/schemas.py`; engine, agent and match values (`Rules`, `BoardSetup`, `Move`, `AgentSpec`, `AgentRegistration`, `DecisionRecord`, `GameRecord`) are used as they are (D25), so the OpenAPI schema types them. |
| Settings | pydantic-settings | `DatabaseSettings` (only the database URL, all migrations need) and `ApiSettings` extending it. Env vars prefixed `HIVE_` or a `.env` file: database URL, S3 endpoint/keys/bucket, model name/version, pool size, budgets. Connection settings have no defaults; `make dev` copies `.env.example` (matching the compose stack) to `.env`. |
| Database | SQLAlchemy 2.x typed ORM (`Mapped[...]`) with its asyncio extension, psycopg 3, Alembic | No SQLModel. The same `postgresql+psycopg://` URL serves the async app and the synchronous Alembic migrations (`hive db upgrade`, `DatabaseSettings.alembic_config()`). JSONB columns hold typed values through `TypedJsonb`; `GameRow.ply_count` is counted in SQL. Relationships are `lazy="raise"` and loaded with `selectinload`. Migrations in `src/hive/api/db/migrations/`. |
| Object storage | Garage via `boto3` (S3 API) | A small async `ObjectStore` with what is used (`delete_prefix`, `check`), running boto3 calls in worker threads through one `request` helper; uploads and downloads come with photos (WP 16). Failed deletions raise `ObjectStoreError`. Tests use `moto`'s in-process S3. |
| Logging | stdlib `logging`, `python-json-logger`, `asgi-correlation-id` | JSON lines with the `X-Request-ID` request ID, including uvicorn's access log (written when the response starts, so without latency; route and latency metrics come from Prometheus in WP 12). No `BaseHTTPMiddleware`, which breaks streaming. No `print` (`T20`). |
| Metrics | `prometheus-client` | `/metrics` endpoint. |
| Local dev | `deploy/compose.yaml` with Postgres and single-node Garage | `make dev` starts compose, migrates, and runs `hive serve --reload` (plus `vite` from WP 13). Garage bootstraps itself with `server --single-node --default-bucket` (v2.3+), creating the layout, the `hive` bucket and a fixed dev key, which `.env.example` matches. |
| Tests | pytest with the `anyio` plugin; `httpx2.AsyncClient` over `ASGITransport`; `moto` for S3; testcontainers Postgres | Async tests (`pytestmark = pytest.mark.anyio`) share one event loop per session (`anyio_backend` is session-scoped), so the async engine outlives single tests. No SQLite, so JSONB and Postgres behaviour are tested for real. A session-scoped container is migrated from scratch; each test runs in a rolled-back transaction, and every request opens its own session in it. One test goes through the real session dependency and cleans up after itself. Without Docker the database tests skip locally (never in CI), or run against `HIVE_TEST_DATABASE_URL`, whose schema they drop and recreate. |

## Code structure (WP 10)

- **Routes** (`api/routes/`) are thin `async def` handlers: parse the request, call a
  service method, build the response model. Every resource router carries the full
  `API_PREFIX` (`/api`) itself, since FastAPI keeps route paths relative to the defining
  router and logs and metrics label requests by that path.
- **Services** (`api/games.py`, `GameService`) hold the behaviour on stored games and
  build the rows; request models only validate. Each method that writes commits before it
  returns, so a call is one unit of work. Deleting a game commits the rows first, then
  deletes its photo objects; a failure there is logged and leaves orphaned objects that a
  later sweep of `photos/<id>/` prefixes without a game can remove. WP 11 (moves,
  undo, state) and WP 12 (committing agent decisions) extend the service rather than the
  routes.
- **Moves (WP 11)**: the API's `ply` is always the record ply, the index into the stored
  moves, also for games from the board editor (where the engine's own ply starts at the
  setup's). Positions are replayed from the stored moves on every request. Writes load
  the game with `get_game(lock=True)` (`SELECT ... FOR UPDATE`), so moves and undos of
  one game run one at a time and `expected_ply` checks cannot race. Every move ends in
  `GameService.append_move`, which checks legality, stores the move and finishes the
  game; WP 12 commits agent decisions through it with their `DecisionRecord`.
- **Errors** (`api/errors.py`): services raise `ApiError` subclasses (`GameNotFoundError`,
  `PlyConflictError`, `MoveNotLegalError`, ...), which one exception handler turns into
  an `ErrorResponse` (`{code, detail}`) with the error's status code. Routes declare them
  with `error_responses(...)`, so the generated client knows every error shape. A 422
  response allows both `ErrorResponse` and FastAPI's `HTTPValidationError`, since
  declaring a 422 replaces FastAPI's own.
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
  rules         jsonb     -- Rules
  setup         jsonb null -- BoardSetup from the editor, or null for the initial state
  white_player  jsonb     -- {"type": "human"} or {"type": "agent", "spec": AgentSpec, "budget_s": 5.0}
  black_player  jsonb
  result        text null -- white | black | draw
  created_at    timestamptz
  updated_at    timestamptz

move
  game_id       uuid fk → game (on delete cascade)
  ply           int       -- pk (game_id, ply)
  move          jsonb     -- Move, or JSON null for a pass
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
| GET | `/games/{id}/state?ply=N` | 11 | `GamePosition`: board (stacks), hands, side to move, `ply` and `ply_count`, result, last move (the stored move, so a pass is told apart from the start), `movable_pieces` (with at least one target), `placeable_coords`, `placeable_piece_types` and `must_pass`. The move lists are empty once the game ended. `ply` (default: latest) enables replay; past the last move is 422 `ply_out_of_range`. |
| GET | `/games/{id}/targets?q=&r=` | 11 | Legal targets of the top piece at `(q, r)` in the latest position. 404 `coordinate_empty`; 422 `piece_not_movable` with the reason from `Rules.immobility_reason` (other side's piece, queen not placed, one-hive rule, no target, game over). |
| POST | `/games/{id}/moves` | 11 | Play a move: `{move, source, photo_id?, expected_ply, allow_agent_side}`, returning the new `GamePosition` (201). `source` is `manual` or `photo`; `photo_id` is required with `photo` only, must belong to the game, and is marked `confirmed`. Checks in order: 409 `ply_conflict` on an `expected_ply` mismatch, 409 `game_not_active` for finished or abandoned games, 409 `agent_turn` when an agent plays the side to move (any source) unless `allow_agent_side`, 422 `move_not_legal` with the reason from `Rules.illegal_move_reason`. Sets status `finished` and the result when the game ends. |
| DELETE | `/games/{id}/moves/last` | 11 | Undo the last move, returning the new `GamePosition`. Optional `expected_ply` (409 `ply_conflict`); 409 `no_move_to_undo` without moves. Reopens finished games (status `active`, no result); abandoned games stay abandoned. Unconfirms the move's photo. |
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
  Open short sessions with `database.session_factory()`: one to load the game before
  streaming, one to commit the decision at the end. No connection is held during the
  stream.
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
