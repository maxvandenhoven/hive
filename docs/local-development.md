# Local development

The root [README](../README.md) has separate starting points for playing in the browser and working on the engine. This page covers the services and configuration behind the browser workflow.

## Run the app

Install Python 3.13, uv, Node.js 24 or newer, npm, and Docker with Compose. From the repository root, run the following commands.

```sh
make sync
make dev
```

`make sync` installs all Python extras and development dependencies, then runs `npm ci` in `frontend/`. `make dev` copies `.env.example` to `.env` only if `.env` does not already exist. It starts PostgreSQL and Garage with `deploy/compose.yaml`, waits for their health checks, and runs `uv run hive db upgrade` before starting the app.

The browser uses `http://localhost:5173`. Vite proxies `/api` requests to FastAPI at `http://127.0.0.1:8000`, where interactive API documentation is available at `/docs`.

Stop the app with Ctrl+C, then stop the backing services separately.

```sh
make dev-down
```

Compose keeps its named volumes, so restarting does not discard saved games. Ports 5432 and 3900 must be free for the default database and object store, as well as ports 8000 and 5173 for the app.

## Configure services

API settings are read from `HIVE_` environment variables and `.env` in the working directory. The local values in [.env.example](../.env.example) match [deploy/compose.yaml](../deploy/compose.yaml). They are development credentials, not deployment secrets. The app needs the database URL, S3 endpoint, access key ID, and secret access key even when you only use manual move entry.

Additional settings include `HIVE_POOL_SIZE`, `HIVE_POOL_WAIT_S`, and `HIVE_MAX_BUDGET_S` for agent workers, and `HIVE_LOG_LEVEL` for logging. See [ApiSettings](../src/hive/api/settings.py) for the complete definition and defaults.

If you use your own services, configure `.env` or environment variables, apply migrations, and start the two app processes in separate terminals. This avoids starting the bundled Compose services.

```sh
uv run hive db upgrade
uv run hive serve --reload
```

```sh
npm --prefix frontend run dev
```

## Serve a frontend build

FastAPI can serve the built frontend itself, without Vite. With the backing services configured and migrated, run the following commands from the repository root.

```sh
npm --prefix frontend run build
uv run hive serve
```

Open `http://127.0.0.1:8000`. The default frontend directory is `frontend/dist`, and `HIVE_FRONTEND_DIR` selects another build directory. If that directory does not exist, FastAPI serves only the API. This is a local serving workflow, not a complete production deployment.

## Check API changes

`make api-client` exports the OpenAPI schema without starting a server and regenerates `frontend/src/api/schema.ts`. Run it after changing API schemas, then review the generated diff and run the frontend checks.

```sh
make api-client
npm --prefix frontend run typecheck
npm --prefix frontend test
```

API integration tests normally use a temporary PostgreSQL container and an in-process S3 mock, not your development Garage bucket. `HIVE_TEST_DATABASE_URL` can point them at a separate PostgreSQL database when Docker is not available, but the test fixture **drops and recreates that database's schema**. Never set it to a database whose data you want to keep.
