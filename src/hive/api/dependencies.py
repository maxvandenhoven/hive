"""FastAPI dependencies that hand route handlers the database, store and services.

They are `async` even when they do not await, because FastAPI runs synchronous
dependencies in a worker thread.
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from hive.api.db.session import Database
from hive.api.games import GameService
from hive.api.storage import ObjectStore


async def get_database(request: Request) -> Database:
    """Get the database of the app.

    Args:
        request: The request being handled.

    Returns:
        The database the lifespan handler opened.
    """
    return request.app.state.database


async def get_store(request: Request) -> ObjectStore:
    """Get the object store of the app.

    Args:
        request: The request being handled.

    Returns:
        The object store the lifespan handler opened.
    """
    return request.app.state.store


async def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncGenerator[AsyncSession]:
    """Open a database session for one route handler.

    Args:
        database: The database of the app.

    Yields:
        The session, closed when the handler returns; uncommitted changes are rolled back.
    """
    async with database.session() as session:
        yield session


type DatabaseDependency = Annotated[Database, Depends(get_database)]
"""The database of the app, as a route handler parameter."""

type StoreDependency = Annotated[ObjectStore, Depends(get_store)]
"""The object store of the app, as a route handler parameter."""

type SessionDependency = Annotated[AsyncSession, Depends(get_session, scope="function")]
"""A database session, as a route handler parameter.

Scoped to the handler function rather than the request, so the session is closed before
the response is sent and a streaming response never holds a pooled connection."""


async def get_game_service(
    session: SessionDependency, store: StoreDependency
) -> GameService:
    """Create the game service of a route handler.

    Args:
        session: The database session of the handler.
        store: The object store of the app.

    Returns:
        The service.
    """
    return GameService(session=session, store=store)


type GameServiceDependency = Annotated[GameService, Depends(get_game_service)]
"""The game service, as a route handler parameter."""
