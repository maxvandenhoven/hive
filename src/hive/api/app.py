"""The FastAPI app factory and the lifespan that opens the database, store and pool."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI

from hive import __version__
from hive.api.db.session import Database
from hive.api.errors import ApiError, handle_api_error
from hive.api.frontend import FrontendFiles
from hive.api.metrics import ApiMetrics, HttpMetricsMiddleware
from hive.api.observability import REQUEST_ID_HEADER
from hive.api.pool import AgentPool
from hive.api.routes import agents, games, health, metrics
from hive.api.settings import ApiSettings
from hive.api.storage import ObjectStore

logger = logging.getLogger(__name__)


def create_app(
    settings: ApiSettings | None = None,
    *,
    database: Database | None = None,
    store: ObjectStore | None = None,
    pool: AgentPool | None = None,
) -> FastAPI:
    """Create the API app.

    The database, object store and worker pool are opened by the lifespan handler, so
    creating the app connects to nothing and starts no process.

    Args:
        settings: The service settings, or `None` to read them from the environment.
        database: The database to use instead of the one in the settings, for tests.
            It is not disposed on shutdown.
        store: The object store to use instead of the one in the settings, for tests.
        pool: The worker pool to use instead of one sized by the settings, for tests.
            It is not closed on shutdown.

    Returns:
        The app.
    """
    resolved_settings = settings or ApiSettings()
    app_metrics = ApiMetrics()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Open the database, object store and worker pool for the lifetime of the app.

        Args:
            app: The app, whose state receives the `database`, `store` and `pool`.

        Yields:
            Control while the app serves requests; the database is disposed and the
            pool closed afterwards unless they were passed in.
        """
        app.state.database = database or Database.from_url(resolved_settings.database_url)
        app.state.store = store or ObjectStore.from_settings(resolved_settings)
        app.state.pool = pool or AgentPool(
            capacity=resolved_settings.pool_size, wait_s=resolved_settings.pool_wait_s
        )
        app_metrics.watch_pool(app.state.pool)

        try:
            yield
        finally:
            if pool is None:
                await app.state.pool.close()

            if database is None:
                await app.state.database.engine.dispose()

    app = FastAPI(
        title="Hive",
        version=__version__,
        lifespan=lifespan,
        # Operation IDs are the handler names, which the generated client uses.
        generate_unique_id_function=lambda route: route.name,
    )
    app.state.settings = resolved_settings
    app.state.metrics = app_metrics
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_middleware(HttpMetricsMiddleware, metrics=app_metrics)
    app.add_middleware(CorrelationIdMiddleware, header_name=REQUEST_ID_HEADER)
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(agents.router)
    app.include_router(games.router)

    # The frontend is mounted last, so every route above takes precedence over its files.
    frontend_dir = resolved_settings.frontend_dir

    if frontend_dir is not None and frontend_dir.is_dir():
        app.mount("/", FrontendFiles(directory=str(frontend_dir)), name="frontend")
    elif frontend_dir is not None:
        logger.info("No frontend build at `%s`; serving the API only.", frontend_dir)

    return app
