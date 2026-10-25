import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect

from hive.api.db.models import Base
from hive.api.db.session import Database

pytestmark = pytest.mark.anyio


def schema_differences(connection: Connection) -> list[object]:
    """Compare the schema of the database with the ORM models."""
    context = MigrationContext.configure(connection, opts={"compare_type": True})

    return compare_metadata(context, Base.metadata)


def table_names(connection: Connection) -> set[str]:
    """List the tables of the database."""
    return set(inspect(connection).get_table_names())


async def test_schema_matches_models(database: Database) -> None:
    async with database.engine.connect() as connection:
        assert await connection.run_sync(schema_differences) == []


async def test_downgrade_and_upgrade_from_scratch(database: Database) -> None:
    await database.downgrade("base")

    async with database.engine.connect() as connection:
        assert await connection.run_sync(table_names) == {"alembic_version"}

    await database.upgrade()

    async with database.engine.connect() as connection:
        assert await connection.run_sync(table_names) == {
            "alembic_version",
            "game",
            "move",
            "photo",
        }
