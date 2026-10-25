"""The FastAPI app factory and the lifespan that opens the database and object store."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from hive import __version__
from hive.api.db.session import Database
from hive.api.observability import RequestLoggingMiddleware
from hive.api.routes import agents, games, health
from hive.api.settings import ApiSettings
from hive.api.storage import ObjectStore, S3ObjectStore


def create_app(
    settings: ApiSettings | None = None,
    *,
    database: Database | None = None,
    store: ObjectStore | None = None,
) -> FastAPI:
    """Create the API app.

    The database and object store are opened by the lifespan handler, so creating the
    app connects to nothing.

    Args:
        settings: The service settings, or `None` to read them from the environment.
        database: The database to use instead of the one in the settings, for tests.
            It is not disposed on shutdown.
        store: The object store to use instead of the one in the settings, for tests.

    Returns:
        The app.
    """
    resolved_settings = settings or ApiSettings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Open the database and object store for the lifetime of the app.

        Args:
            app: The app, whose state receives the `database` and `store`.

        Yields:
            Control while the app serves requests; the database is disposed afterwards
            unless it was passed in.
        """
        app.state.database = database or Database.from_url(resolved_settings.database_url)
        app.state.store = store or S3ObjectStore.from_settings(resolved_settings)

        try:
            yield
        finally:
            if database is None:
                app.state.database.dispose()

    app = FastAPI(title="Hive", version=__version__, lifespan=lifespan)
    app.state.settings = resolved_settings
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(health.router)
    app.include_router(agents.router)
    app.include_router(games.router)

    return app
