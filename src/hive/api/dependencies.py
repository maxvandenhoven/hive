"""FastAPI dependencies that hand route handlers the database, store and services.

They are `async` even when they do not await, because FastAPI runs synchronous
dependencies in a worker thread.
"""

import uuid
from collections.abc import AsyncGenerator, Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from hive.api.db.session import Database
from hive.api.games import GameService
from hive.api.metrics import ApiMetrics
from hive.api.pool import AgentPool
from hive.api.schemas import ThinkRequest
from hive.api.settings import ApiSettings
from hive.api.storage import ObjectStore
from hive.api.thinking import AgentThinking, ThinkingPlan


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


async def get_settings(request: Request) -> ApiSettings:
    """Get the settings of the app.

    Args:
        request: The request being handled.

    Returns:
        The settings the app was created with.
    """
    return request.app.state.settings


async def get_pool(request: Request) -> AgentPool:
    """Get the agent worker pool of the app.

    Args:
        request: The request being handled.

    Returns:
        The pool the lifespan handler created.
    """
    return request.app.state.pool


async def get_metrics(request: Request) -> ApiMetrics:
    """Get the metrics of the app.

    Args:
        request: The request being handled.

    Returns:
        The metrics the app was created with.
    """
    return request.app.state.metrics


async def get_session_factory(
    database: Annotated[Database, Depends(get_database)],
) -> Callable[[], AsyncSession]:
    """Get what opens database sessions, for handlers that open their own.

    Args:
        database: The database of the app.

    Returns:
        The session factory of the database.
    """
    return database.session_factory


type SessionFactoryDependency = Annotated[
    Callable[[], AsyncSession], Depends(get_session_factory)
]
"""Opens database sessions, as a route handler parameter. Streaming handlers open short
sessions with it, since a session dependency is closed while their stream still runs."""


async def get_session(
    session_factory: SessionFactoryDependency,
) -> AsyncGenerator[AsyncSession]:
    """Open a database session for one route handler.

    Args:
        session_factory: Opens database sessions.

    Yields:
        The session, closed when the handler returns; uncommitted changes are rolled back.
    """
    async with session_factory() as session:
        yield session


type DatabaseDependency = Annotated[Database, Depends(get_database)]
"""The database of the app, as a route handler parameter."""

type SettingsDependency = Annotated[ApiSettings, Depends(get_settings)]
"""The settings of the app, as a route handler parameter."""

type PoolDependency = Annotated[AgentPool, Depends(get_pool)]
"""The agent worker pool of the app, as a route handler parameter."""

type MetricsDependency = Annotated[ApiMetrics, Depends(get_metrics)]
"""The metrics of the app, as a route handler parameter."""

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


async def start_thinking(
    game_id: uuid.UUID,
    body: ThinkRequest,
    session_factory: SessionFactoryDependency,
    store: StoreDependency,
    settings: SettingsDependency,
    pool: PoolDependency,
    metrics: MetricsDependency,
) -> AsyncGenerator[AgentThinking]:
    """Check a thinking request and start the decision, before the stream starts.

    Errors raised here, such as an unknown game or a busy pool, become error responses.
    The dependency lives until the response ends, so the worker is held for the whole
    stream and returned to the pool afterwards.

    Args:
        game_id: The game ID.
        body: The thinking request.
        session_factory: Opens the session that loads the game.
        store: The object store of the app.
        settings: The settings of the app, with the longest budget.
        pool: The agent worker pool of the app.
        metrics: The metrics of the app.

    Yields:
        The running decision, stopped early if the response ends first.
    """
    async with session_factory() as session:
        plan = await ThinkingPlan.load(
            games=GameService(session=session, store=store),
            game_id=game_id,
            body=body,
            max_budget_s=settings.max_budget_s,
        )

    async with AgentThinking.start(plan=plan, pool=pool, metrics=metrics) as thinking:
        yield thinking


type ThinkingDependency = Annotated[AgentThinking, Depends(start_thinking)]
"""A running agent decision for a thinking request, as a route handler parameter."""
