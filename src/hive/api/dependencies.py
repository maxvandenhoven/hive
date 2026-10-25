"""FastAPI dependencies that hand route handlers the database session and object store."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from hive.api.db.session import Database
from hive.api.storage import ObjectStore


def get_database(request: Request) -> Database:
    """Get the database of the app.

    Args:
        request: The request being handled.

    Returns:
        The database the lifespan handler opened.
    """
    return request.app.state.database


def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> Iterator[Session]:
    """Open a database session for one request.

    Args:
        database: The database of the app.

    Yields:
        The session, closed after the response; uncommitted changes are rolled back.
    """
    with database.session() as session:
        yield session


def get_store(request: Request) -> ObjectStore:
    """Get the object store of the app.

    Args:
        request: The request being handled.

    Returns:
        The object store the lifespan handler opened.
    """
    return request.app.state.store


type DatabaseDependency = Annotated[Database, Depends(get_database)]
"""The database of the app, as a route handler parameter."""

type SessionDependency = Annotated[Session, Depends(get_session)]
"""A database session for the request, as a route handler parameter."""

type StoreDependency = Annotated[ObjectStore, Depends(get_store)]
"""The object store of the app, as a route handler parameter."""
