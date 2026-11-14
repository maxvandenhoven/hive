"""Golden fixtures of the stored and served formats, and a pinned seeded match.

Each test reads a file in `tests/data/golden/` and checks that the current code reads and
writes it unchanged, or plays the same game again. A change that alters one of these on
purpose regenerates the file in the same pull request, as `tests/data/golden/README.md`
describes, so the diff shows what changed.
"""

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql
from typer.testing import CliRunner

from hive import __version__
from hive.agents import factory
from hive.agents.base import SearchInfoValue
from hive.agents.factory import AgentSpec, build_agent, list_agents
from hive.agents.negamax import NegamaxAgent
from hive.api.db.models import TypedJsonb
from hive.api.players import AgentPlayer, HumanPlayer, PlayerConfig
from hive.cli import app
from hive.engine.rules import Rules
from hive.match.gauntlet import GauntletReport
from hive.match.records import DecisionRecord, MatchOutcome, MatchResult
from hive.match.runner import MatchRunner

GOLDEN = Path(__file__).parent / "data" / "golden"
"""The folder of the golden fixtures."""

PINNED_MATCH_MAX_TURNS = 60
"""The turn cap the pinned match was played with, which `MatchResult` does not store."""


def read_golden(name: str) -> Any:
    """Read a golden fixture.

    Args:
        name: The file name in `tests/data/golden/`.

    Returns:
        The parsed JSON.
    """
    return json.loads((GOLDEN / name).read_text())


def search_report(decision: DecisionRecord) -> dict[str, SearchInfoValue] | None:
    """Get the last search report of a decision without the timing-dependent speed.

    Args:
        decision: The decision.

    Returns:
        The depth, nodes, score and principal variation the agent reported last, or
        `None` if it reported none, as for a forced pass.
    """
    if decision.last_info is None:
        return None

    return {key: value for key, value in decision.last_info.items() if key != "nps"}


class TestGauntletReport:
    def test_round_trip(self) -> None:
        data = read_golden("gauntlet_report.json")

        report = GauntletReport.from_json(data)

        assert report.to_json() == data

    def test_aggregates_replays_to_same_report(self) -> None:
        data = read_golden("gauntlet_report.json")
        report = GauntletReport.from_json(data)
        assert report.replays is not None

        rebuilt = GauntletReport.from_results(
            config=report.config, results=report.replays, duration_s=report.duration_s
        )

        assert rebuilt.to_json() == data

    def test_replays_match_summaries(self) -> None:
        report = GauntletReport.from_json(read_golden("gauntlet_report.json"))

        for summary in report.matches:
            replay = report.replay(summary.index)
            state = replay.record.replay()

            assert state.current_ply == summary.plies
            assert replay.outcome is summary.outcome


class TestChampionSpec:
    def test_round_trip(self) -> None:
        data = read_golden("champion_spec.json")

        spec = AgentSpec.parse(data)

        assert spec.to_json() == data

    def test_builds_negamax_agent(self) -> None:
        spec = AgentSpec.from_json(read_golden("champion_spec.json"))

        agent = build_agent(spec=spec, rules=Rules(), seed=0)

        assert isinstance(agent, NegamaxAgent)


class TestAgentParamsSchemas:
    def test_registered_kinds(self) -> None:
        golden = read_golden("agent_params_schemas.json")
        schemas = {agent.kind: agent.params_schema for agent in list_agents()}

        assert schemas == {kind: golden[kind] for kind in schemas}

    def test_test_kinds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test the kinds of `hive.match.testing`, registering them in a registry copy."""
        golden = read_golden("agent_params_schemas.json")
        monkeypatch.setattr(factory, "AGENT_REGISTRY", dict(factory.AGENT_REGISTRY))
        testing = importlib.import_module("hive.match.testing")
        agent_classes = {
            "test-counting": testing.CountingAgent,
            "test-crashes": testing.CrashingAgent,
            "test-illegal": testing.IllegalAgent,
            "test-lingers": testing.LingeringAgent,
            "test-never-submits": testing.NeverSubmitsAgent,
        }

        schemas = {
            kind: factory.AgentRegistration(
                kind=kind, agent_class=agent_class
            ).params_schema
            for kind, agent_class in agent_classes.items()
        }

        assert schemas == {kind: golden[kind] for kind in schemas}
        assert set(golden) == set(schemas) | {agent.kind for agent in list_agents()}


def test_stored_players_round_trip() -> None:
    column = TypedJsonb(PlayerConfig)
    dialect = postgresql.dialect()
    stored = read_golden("players.json")

    players = [column.process_result_value(value, dialect=dialect) for value in stored]

    assert [column.process_bind_param(player, dialect=dialect) for player in players] == (
        stored
    )
    assert {type(player) for player in players} == {HumanPlayer, AgentPlayer}


def test_openapi_output(tmp_path: Path) -> None:
    golden = read_golden("openapi.json")
    output = tmp_path / "openapi.json"

    result = CliRunner().invoke(app, ["openapi", "--output", str(output)])
    schema = json.loads(output.read_text())

    assert result.exit_code == 0
    assert schema["info"].pop("version") == __version__
    golden["info"].pop("version")
    assert schema == golden


class TestPinnedMatch:
    def test_round_trip(self) -> None:
        data = read_golden("pinned_match.json")

        assert MatchResult.from_json(data).to_json() == data

    def test_reproduces_moves_and_outcome(self) -> None:
        pinned = MatchResult.from_json(read_golden("pinned_match.json"))
        runner = MatchRunner(
            rules=pinned.rules,
            white_spec=pinned.white_spec,
            black_spec=pinned.black_spec,
            budget_s=pinned.budget_s,
            max_turns=PINNED_MATCH_MAX_TURNS,
            seed=pinned.seed,
            opening=pinned.opening,
        )

        result = runner.run()

        assert [d.move for d in result.decisions] == [d.move for d in pinned.decisions]
        assert [d.seed for d in result.decisions] == [d.seed for d in pinned.decisions]
        assert [search_report(d) for d in result.decisions] == [
            search_report(d) for d in pinned.decisions
        ]
        assert result.outcome is pinned.outcome is MatchOutcome.WIN
        assert result.winner is pinned.winner
