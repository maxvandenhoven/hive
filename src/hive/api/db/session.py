"""Database connections, sessions and schema migrations.

The app uses SQLAlchemy's asyncio extension on psycopg 3, so database calls never block
the event loop that also serves the agent thinking streams. Alembic runs synchronously
over the same connection through `AsyncConnection.run_sync`.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

MIGRATIONS_LOCATION = "hive.api.db:migrations"
"""The Alembic script location, as a package resource so it works when installed."""

CONNECT_TIMEOUT_S = 5
"""The seconds to wait for a new connection, so readiness checks fail quickly."""


class Database:
    """A Postgres database: its connection pool, sessions and migrations.

    Attributes:
        engine: The SQLAlchemy engine with the connection pool.
        session_factory: Creates sessions bound to the engine.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        """Wrap an engine.

        Args:
            engine: The SQLAlchemy engine.
        """
        self.engine = engine
        self.session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    @classmethod
    def from_url(cls, url: str) -> "Database":
        """Connect to a database lazily: no connection is opened until one is needed.

        Args:
            url: The SQLAlchemy URL, for example `postgresql+psycopg://...`.

        Returns:
            The database.
        """
        engine = create_async_engine(
            url, pool_pre_ping=True, connect_args={"connect_timeout": CONNECT_TIMEOUT_S}
        )

        return cls(engine)

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        """Open a session that is closed afterwards, rolling back anything uncommitted.

        Yields:
            The session. It holds a pooled connection only between its first query and
            the next commit, rollback or close.
        """
        async with self.session_factory() as session:
            yield session

    async def check(self) -> None:
        """Check that the database accepts queries, for readiness probes.

        Raises:
            sqlalchemy.exc.OperationalError: If the database cannot be reached.
        """
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def upgrade(self, revision: str = "head") -> None:
        """Migrate the schema up to a revision.

        Args:
            revision: The Alembic revision to migrate to.
        """
        async with self.engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: command.upgrade(
                    alembic_config(sync_connection), revision
                )
            )

    async def downgrade(self, revision: str) -> None:
        """Migrate the schema down to a revision.

        Args:
            revision: The Alembic revision to migrate to, for example `base`.
        """
        async with self.engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: command.downgrade(
                    alembic_config(sync_connection), revision
                )
            )

    async def dispose(self) -> None:
        """Close every pooled connection."""
        await self.engine.dispose()


def alembic_config(connection: Connection) -> Config:
    """Build the Alembic configuration for migrating over an open connection.

    Args:
        connection: The synchronous SQLAlchemy connection the migration environment uses.

    Returns:
        The configuration, with the packaged migrations and the connection attached.
    """
    config = Config()
    config.set_main_option("script_location", MIGRATIONS_LOCATION)
    config.attributes["connection"] = connection

    return config
