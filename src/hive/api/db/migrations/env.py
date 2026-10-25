"""Alembic migration environment.

Migrations run over the connection that `Database.upgrade` attaches to the configuration.
Run from the command line (`uv run alembic ...` with the root `alembic.ini`), they connect
to `HIVE_DATABASE_URL`.
"""

from alembic import context
from sqlalchemy import Connection, create_engine

from hive.api.db.models import Base
from hive.api.settings import ApiSettings


def command_line_database_url() -> str:
    """Read the database URL for a migration run from the command line.

    Returns:
        The database URL from `HIVE_` environment variables or `.env`.
    """
    return ApiSettings().database_url


def run_migrations(connection: Connection) -> None:
    """Run the migrations over a connection.

    Args:
        connection: The database connection.
    """
    context.configure(
        connection=connection, target_metadata=Base.metadata, compare_type=True
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the migrations over the attached connection, or a new one from the settings."""
    connection = context.config.attributes.get("connection")

    if connection is not None:
        run_migrations(connection)
        return

    engine = create_engine(command_line_database_url())

    with engine.connect() as new_connection:
        run_migrations(new_connection)

    engine.dispose()


if context.is_offline_mode():
    context.configure(url=command_line_database_url(), target_metadata=Base.metadata)

    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
