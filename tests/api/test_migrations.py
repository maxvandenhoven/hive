from collections.abc import Generator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.pool import NullPool

from hive.api.db.models import DatabaseBase
from hive.api.settings import DatabaseSettings


@pytest.fixture(scope="function")
def engine(postgres_url: str) -> Generator[Engine]:
    """Yield a synchronous engine on the migrated test database."""
    engine = create_engine(postgres_url, poolclass=NullPool)
    yield engine
    engine.dispose()


def test_schema_matches_models(engine: Engine) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})

        assert compare_metadata(context, DatabaseBase.metadata) == []


def test_downgrade_and_upgrade_from_scratch(postgres_url: str, engine: Engine) -> None:
    config = DatabaseSettings(_env_file=None, database_url=postgres_url).alembic_config()
    command.downgrade(config, "base")

    assert set(inspect(engine).get_table_names()) == {"alembic_version"}

    command.upgrade(config, "head")

    assert set(inspect(engine).get_table_names()) == {
        "alembic_version",
        "game",
        "move",
        "photo",
    }


def test_offline_migration_writes_sql(capsys: pytest.CaptureFixture[str]) -> None:
    url = "postgresql+psycopg://hive@db.invalid/hive"
    config = DatabaseSettings(_env_file=None, database_url=url).alembic_config()
    command.upgrade(config, "head", sql=True)

    assert "CREATE TABLE game" in capsys.readouterr().out
