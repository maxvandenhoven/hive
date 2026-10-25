# API and data

The API is a FastAPI app in `src/hive/api/` (extra `api`). It owns persistence, the agent
worker pool and the photo pipeline, and serves the built frontend. The engine stays
stateless per request: load the game's moves from Postgres, replay them with
`GameRecord.replay()`, answer, and store any new move.

## Stack

| Concern | Choice | Notes |
|---|---|---|
| Web framework | FastAPI + uvicorn | Pydantic v2 request/response models in `api/schemas.py`, separate from DB models. |
| Settings | pydantic-settings | Env vars prefixed `HIVE_`: database URL, S3 endpoint/keys/bucket, model name/version, pool size, budgets. |
| Database | SQLAlchemy 2.0 typed ORM (`Mapped[...]`), psycopg 3, Alembic | No SQLModel. Migrations in `src/hive/api/db/migrations/`. |
| Object storage | Garage via `boto3` (S3 API) | Wrapped in a `PhotoStore` / `ObjectStore` protocol with an in-memory fake for tests. |
| Logging | stdlib `logging` with a JSON formatter | Request ID middleware; no `print` (`T20`). |
| Metrics | `prometheus-client` | `/metrics` endpoint. |
| Local dev | `deploy/compose.yaml` with Postgres and single-node Garage | `make dev` starts compose, migrates, and runs `hive serve --reload` (plus `vite` from WP 13). Garage bootstraps itself with `server --single-node --default-bucket` (v2.3+), creating the layout, the `hive` bucket and a fixed dev key; the `ApiSettings` defaults match the stack. |
| Tests | pytest; fakes for unit tests; testcontainers Postgres for API tests | No SQLite, so JSONB and Postgres behaviour are tested for real. A session-scoped container is migrated from scratch; each test runs in a rolled-back transaction. Without Docker the database tests skip locally (never in CI), or run against `HIVE_TEST_DATABASE_URL`, whose schema they drop and recreate. |

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
- The pool is shut down cleanly on app shutdown (lifespan handler).

## Observability (WP 12)

- JSON logs with request ID, game ID, route, latency; one log line per decision with the
  `DecisionRecord` fields; one per photo match (reader, latency, top score, margin).
- Metrics: HTTP request histograms by route and status, the decision metrics listed in
  `agents-and-matches.md`, pool gauges, `hive_photo_read_seconds{reader}`,
  `hive_photo_match_total{outcome}` (auto, candidates, failed).
- A `ServiceMonitor` scrapes `/metrics` in the cluster (WP 26).
