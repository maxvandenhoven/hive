import os
from collections.abc import Generator

import docker
import pytest
from docker.errors import DockerException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from hive.api.app import create_app
from hive.api.db.session import Database
from hive.api.dependencies import get_session
from hive.api.settings import ApiSettings
from hive.api.storage import InMemoryObjectStore

POSTGRES_IMAGE = "postgres:17-alpine"

UNREACHABLE_DATABASE_URL = "postgresql+psycopg://hive:hive@127.0.0.1:1/hive"
"""A database URL that refuses connections immediately."""


@pytest.fixture(scope="session")
def postgres_url() -> Generator[str]:
    """Start a Postgres container for the test session and yield its URL.

    Uses the database at `HIVE_TEST_DATABASE_URL` instead if it is set; its schema is
    dropped and recreated. Skips the tests that need a database when Docker is not
    available, except in CI.
    """
    external_url = os.environ.get("HIVE_TEST_DATABASE_URL")

    if external_url:
        yield external_url
        return

    try:
        docker.from_env().ping()
    except DockerException as e:
        if os.environ.get("CI"):
            raise

        pytest.skip(f"Docker is not available: {e}")

    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def database(postgres_url: str) -> Generator[Database]:
    """Migrate the test database from scratch and yield it."""
    database = Database.from_url(postgres_url)
    database.downgrade("base")
    database.upgrade()
    yield database
    database.dispose()


@pytest.fixture(scope="function")
def session(database: Database) -> Generator[Session]:
    """Yield a session whose changes, commits included, are rolled back after the test."""
    with database.engine.connect() as connection:
        transaction = connection.begin()
        session = Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        yield session
        session.close()
        transaction.rollback()


@pytest.fixture(scope="function")
def store() -> InMemoryObjectStore:
    """Build an empty in-memory object store."""
    return InMemoryObjectStore()


@pytest.fixture(scope="function")
def client(
    database: Database, session: Session, store: InMemoryObjectStore
) -> Generator[TestClient]:
    """Yield a client of an app on the test database, with every request in `session`."""
    app = create_app(ApiSettings(), database=database, store=store)
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="function")
def offline_client(store: InMemoryObjectStore) -> Generator[TestClient]:
    """Yield a client of an app whose database refuses connections."""
    database = Database.from_url(UNREACHABLE_DATABASE_URL)
    app = create_app(ApiSettings(), database=database, store=store)

    with TestClient(app) as client:
        yield client

    database.dispose()
