"""The FastAPI app factory and the lifespan that opens the database and object store."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.routing import APIRoute

from hive import __version__
from hive.api.db.session import Database
from hive.api.errors import ApiError, handle_api_error
from hive.api.observability import REQUEST_ID_HEADER, AccessLogMiddleware
from hive.api.routes import agents, games, health
from hive.api.settings import ApiSettings
from hive.api.storage import ObjectStore


def operation_id(route: APIRoute) -> str:
    """Name the OpenAPI operation of a route after its handler function.

    The generated frontend client uses these names, so they must stay stable and unique;
    FastAPI's default appends the path and method.

    Args:
        route: The route.

    Returns:
        The name of the handler function, for example `create_game`.
    """
    return route.name


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
        app.state.store = store or ObjectStore.from_settings(resolved_settings)

        try:
            yield
        finally:
            if database is None:
                await app.state.database.dispose()

    app = FastAPI(
        title="Hive",
        version=__version__,
        lifespan=lifespan,
        generate_unique_id_function=operation_id,
    )
    app.state.settings = resolved_settings
    app.add_exception_handler(ApiError, handle_api_error)
    # The last middleware added is the outermost, so the access log has the request ID.
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CorrelationIdMiddleware, header_name=REQUEST_ID_HEADER)
    app.include_router(health.router)
    app.include_router(agents.router)
    app.include_router(games.router)

    return app
