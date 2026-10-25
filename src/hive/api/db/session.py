"""Database connections, sessions and schema migrations."""

from collections.abc import Generator
from contextlib import contextmanager

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

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

    def __init__(self, engine: Engine) -> None:
        """Wrap an engine.

        Args:
            engine: The SQLAlchemy engine.
        """
        self.engine = engine
        self.session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    @classmethod
    def from_url(cls, url: str) -> "Database":
        """Connect to a database lazily: no connection is opened until one is needed.

        Args:
            url: The SQLAlchemy URL, for example `postgresql+psycopg://...`.

        Returns:
            The database.
        """
        engine = create_engine(
            url, pool_pre_ping=True, connect_args={"connect_timeout": CONNECT_TIMEOUT_S}
        )

        return cls(engine)

    @contextmanager
    def session(self) -> Generator[Session]:
        """Open a session that is closed afterwards, rolling back anything uncommitted.

        Yields:
            The session.
        """
        with self.session_factory() as session:
            yield session

    def check(self) -> None:
        """Check that the database accepts queries, for readiness probes.

        Raises:
            sqlalchemy.exc.OperationalError: If the database cannot be reached.
        """
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def upgrade(self, revision: str = "head") -> None:
        """Migrate the schema up to a revision.

        Args:
            revision: The Alembic revision to migrate to.
        """
        with self.engine.begin() as connection:
            command.upgrade(alembic_config(connection), revision)

    def downgrade(self, revision: str) -> None:
        """Migrate the schema down to a revision.

        Args:
            revision: The Alembic revision to migrate to, for example `base`.
        """
        with self.engine.begin() as connection:
            command.downgrade(alembic_config(connection), revision)

    def dispose(self) -> None:
        """Close every pooled connection."""
        self.engine.dispose()


def alembic_config(connection: Connection) -> Config:
    """Build the Alembic configuration for migrating over an open connection.

    Args:
        connection: The SQLAlchemy connection the migration environment uses.

    Returns:
        The configuration, with the packaged migrations and the connection attached.
    """
    config = Config()
    config.set_main_option("script_location", MIGRATIONS_LOCATION)
    config.attributes["connection"] = connection

    return config
