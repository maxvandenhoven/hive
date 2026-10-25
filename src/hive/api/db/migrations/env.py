"""Alembic migration environment.

Migrations run synchronously over their own connection to the URL that
`DatabaseSettings.alembic_config` attaches, or, run from the command line
(`uv run alembic ...` with the root `alembic.ini`), to `HIVE_DATABASE_URL`.
"""

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from hive.api.db.models import DatabaseBase
from hive.api.settings import DatabaseSettings


def database_url() -> str:
    """Get the URL of the database to migrate.

    Returns:
        The attached URL, or `HIVE_DATABASE_URL` from the environment or `.env`.
    """
    return (
        context.config.attributes.get("database_url") or DatabaseSettings().database_url
    )


def run_migrations() -> None:
    """Run the migrations, offline as SQL or online over a new connection."""
    if context.is_offline_mode():
        context.configure(url=database_url(), target_metadata=DatabaseBase.metadata)

        with context.begin_transaction():
            context.run_migrations()

        return

    engine = create_engine(database_url(), poolclass=NullPool)

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=DatabaseBase.metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


run_migrations()
