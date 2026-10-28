import json
import uuid
from collections.abc import Generator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text
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


def test_upgrade_sets_board_location_and_pending(
    postgres_url: str, engine: Engine
) -> None:
    config = DatabaseSettings(_env_file=None, database_url=postgres_url).alembic_config()
    agent = json.dumps({"type": "agent", "spec": {"kind": "random"}, "budget_s": 1.0})
    human = json.dumps({"type": "human"})
    games = {
        "agents": (uuid.uuid4(), agent, agent),
        "human_white": (uuid.uuid4(), human, agent),
        "human_black": (uuid.uuid4(), agent, human),
    }
    command.downgrade(config, "0001")

    try:
        with engine.begin() as connection:
            for game_id, white, black in games.values():
                connection.execute(
                    text(
                        "INSERT INTO game (id, name, status, rules, white_player, "
                        "black_player) VALUES (:id, 'Old', 'active', '{}', "
                        "CAST(:white AS jsonb), CAST(:black AS jsonb))"
                    ),
                    {"id": game_id, "white": white, "black": black},
                )

            connection.execute(
                text(
                    "INSERT INTO move (game_id, ply, move, source) "
                    "VALUES (:id, 0, 'null', 'agent')"
                ),
                {"id": games["human_white"][0]},
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            locations = dict(
                connection.execute(text("SELECT id, board_location FROM game")).all()
            )
            pending = connection.execute(text("SELECT pending FROM move")).scalars()

            assert {name: locations[game[0]] for name, game in games.items()} == {
                "agents": "screen",
                "human_white": "table",
                "human_black": "table",
            }
            assert list(pending) == [False]
    finally:
        command.upgrade(config, "head")

        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM game WHERE id = ANY(:ids)"),
                {"ids": [game[0] for game in games.values()]},
            )


def test_downgrade_drops_hint_agents(postgres_url: str, engine: Engine) -> None:
    config = DatabaseSettings(_env_file=None, database_url=postgres_url).alembic_config()
    game_id = uuid.uuid4()
    hinted = {"type": "human", "hint": {"spec": {"kind": "random"}, "budget_s": 1.0}}

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO game (id, name, status, rules, white_player, "
                    "black_player, board_location) VALUES (:id, 'New', 'active', '{}', "
                    "CAST(:white AS jsonb), CAST(:black AS jsonb), 'table')"
                ),
                {
                    "id": game_id,
                    "white": json.dumps(hinted),
                    "black": json.dumps({"type": "human", "hint": None}),
                },
            )

        command.downgrade(config, "0001")

        with engine.connect() as connection:
            players = connection.execute(
                text("SELECT white_player, black_player FROM game WHERE id = :id"),
                {"id": game_id},
            ).one()

        assert tuple(players) == ({"type": "human"}, {"type": "human"})
    finally:
        command.upgrade(config, "head")

        with engine.begin() as connection:
            connection.execute(text("DELETE FROM game WHERE id = :id"), {"id": game_id})
