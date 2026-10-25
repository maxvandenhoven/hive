from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from hive.api.db.models import Base
from hive.api.db.session import Database


def test_schema_matches_models(database: Database) -> None:
    with database.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_downgrade_and_upgrade_from_scratch(database: Database) -> None:
    database.downgrade("base")

    assert set(inspect(database.engine).get_table_names()) == {"alembic_version"}

    database.upgrade()

    assert set(inspect(database.engine).get_table_names()) == {
        "alembic_version",
        "game",
        "move",
        "photo",
    }
