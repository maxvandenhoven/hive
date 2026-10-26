import os
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager

import boto3
import docker
import httpx2
import pytest
from alembic import command
from docker.errors import DockerException
from fastapi import FastAPI
from moto import mock_aws
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from testcontainers.community.postgres import PostgresContainer

from hive.api.app import create_app
from hive.api.db.session import Database
from hive.api.dependencies import get_session
from hive.api.settings import ApiSettings, DatabaseSettings
from hive.api.storage import S3_CLIENT_CONFIG, ObjectStore

POSTGRES_IMAGE = "postgres:17-alpine"

UNREACHABLE_DATABASE_URL = "postgresql+psycopg://hive:hive@127.0.0.1:1/hive"
"""A database URL that refuses connections immediately."""

BUCKET = "hive"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Run async tests and fixtures on asyncio, in one event loop for the session."""
    return "asyncio"


@pytest.fixture(scope="function")
def settings() -> ApiSettings:
    """Build settings that ignore the environment and `.env`.

    Tests inject the database and object store, so the connection settings are unused.
    """
    return ApiSettings(
        _env_file=None,
        database_url=UNREACHABLE_DATABASE_URL,
        s3_endpoint_url="http://s3.invalid:3900",
        s3_access_key_id="key",
        s3_secret_access_key=SecretStr("secret"),
    )


def migrate_from_scratch(url: str) -> None:
    """Drop the schema of a database and migrate it to the latest revision."""
    config = DatabaseSettings(_env_file=None, database_url=url).alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def postgres_url() -> Generator[str]:
    """Start a Postgres container for the test session, migrated from scratch.

    Uses the database at `HIVE_TEST_DATABASE_URL` instead if it is set; its schema is
    dropped and recreated. Skips the tests that need a database when Docker is not
    available, except in CI.
    """
    external_url = os.environ.get("HIVE_TEST_DATABASE_URL")

    if external_url:
        migrate_from_scratch(external_url)
        yield external_url
        return

    try:
        docker.from_env().ping()
    except DockerException as e:
        if os.environ.get("CI"):
            raise

        pytest.skip(f"Docker is not available: {e}")

    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        url = container.get_connection_url()
        migrate_from_scratch(url)
        yield url


@pytest.fixture(scope="session")
async def database(postgres_url: str) -> AsyncGenerator[Database]:
    """Yield the migrated test database."""
    database = Database.from_url(postgres_url)
    yield database
    await database.engine.dispose()


@pytest.fixture(scope="function")
async def connection(database: Database) -> AsyncGenerator[AsyncConnection]:
    """Yield a connection in a transaction that is rolled back after the test."""
    async with database.engine.connect() as connection:
        transaction = await connection.begin()
        yield connection
        await transaction.rollback()


def join_session(connection: AsyncConnection) -> AsyncSession:
    """Open a session in the transaction of the test, whose commits become savepoints."""
    return AsyncSession(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )


@pytest.fixture(scope="function")
async def session(connection: AsyncConnection) -> AsyncGenerator[AsyncSession]:
    """Yield a session for preparing and checking data in the transaction of the test."""
    async with join_session(connection) as session:
        yield session


@pytest.fixture(scope="function")
def store() -> Generator[ObjectStore]:
    """Yield a store on an empty bucket of an in-process S3 mock."""
    with mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",  # noqa: S106
            config=S3_CLIENT_CONFIG,
        )
        client.create_bucket(Bucket=BUCKET)
        yield ObjectStore(client=client, bucket=BUCKET)


@asynccontextmanager
async def serve(app: FastAPI) -> AsyncGenerator[httpx2.AsyncClient]:
    """Run the lifespan of an app and yield a client that calls it in-process."""
    transport = httpx2.ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        yield client


@pytest.fixture(scope="function")
async def client(
    settings: ApiSettings,
    database: Database,
    connection: AsyncConnection,
    store: ObjectStore,
) -> AsyncGenerator[httpx2.AsyncClient]:
    """Yield a client of an app on the test database.

    Every request gets its own session, joined to the transaction of the test.
    """
    app = create_app(settings=settings, database=database, store=store)

    async def get_test_session() -> AsyncGenerator[AsyncSession]:
        """Open the session of one request in the transaction of the test."""
        async with join_session(connection) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session

    async with serve(app) as client:
        yield client


@pytest.fixture(scope="function")
async def committing_client(
    settings: ApiSettings, postgres_url: str, store: ObjectStore
) -> AsyncGenerator[httpx2.AsyncClient]:
    """Yield a client of an app that opens the test database and its sessions itself.

    Its changes are committed for real, so tests clean up what they create.
    """
    app_settings = settings.model_copy(update={"database_url": postgres_url})
    app = create_app(settings=app_settings, store=store)

    async with serve(app) as client:
        yield client


@pytest.fixture(scope="function")
async def offline_client(
    settings: ApiSettings, store: ObjectStore
) -> AsyncGenerator[httpx2.AsyncClient]:
    """Yield a client of an app whose database refuses connections."""
    database = Database.from_url(UNREACHABLE_DATABASE_URL)
    app = create_app(settings=settings, database=database, store=store)

    async with serve(app) as client:
        yield client

    await database.engine.dispose()
