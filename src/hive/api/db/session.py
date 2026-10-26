"""The database of the app: its async engine, sessions and readiness check.

The app uses SQLAlchemy's asyncio extension on psycopg 3, so database calls never block
the event loop that also serves the agent thinking streams. Migrations run separately and
synchronously through Alembic (see `DatabaseSettings.alembic_config`).
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

CONNECT_TIMEOUT_S = 5
"""The seconds to wait for a new connection, so readiness checks fail quickly."""


class Database:
    """A Postgres database: its connection pool and its sessions.

    Attributes:
        engine: The SQLAlchemy engine with the connection pool.
        session_factory: Creates sessions bound to the engine. A session holds a pooled
            connection only from its first query to the next commit, rollback or close.
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

    async def check(self) -> None:
        """Check that the database accepts queries, for readiness probes.

        Raises:
            sqlalchemy.exc.OperationalError: If the database cannot be reached.
        """
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
