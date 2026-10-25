"""Tests of the match runner, which start real worker processes."""

from pathlib import Path

import pytest

from hive.agents.factory import AgentSpec
from hive.engine.rules import Rules
from hive.engine.state import Move, Player
from hive.match.records import MatchOutcome, MatchResult
from hive.match.runner import MatchRunner, derive_seed
from hive.match.worker import AgentWorkerError

TESTING_MODULE = "hive.match.testing"
"""The test agents, imported only in workers to keep them out of `list_agents`."""


def check_consistent(result: MatchResult, rules: Rules) -> None:
    """Check that the decisions, the record and the outcome of a result agree."""
    state = result.record.replay()
    assert [decision.move for decision in result.decisions] == result.record.moves
    assert [decision.ply for decision in result.decisions] == list(
        range(len(result.decisions))
    )
    winners = rules.winners(state)

    if result.outcome is MatchOutcome.TURN_CAP:
        assert winners is None
    elif result.outcome is MatchOutcome.WIN:
        assert winners == [result.winner]
    else:
        assert winners is not None
        assert len(winners) == 2


def test_derive_seed() -> None:
    assert derive_seed(1, "white") == derive_seed(1, "white")
    assert len({derive_seed(1, "white"), derive_seed(1, "black"), derive_seed(2)}) == 3
    assert 0 <= derive_seed(1, "white") < 2**63


def test_full_match(rules: Rules) -> None:
    runner = MatchRunner(
        rules=rules,
        white_spec=AgentSpec(kind="negamax", params={"depth": 2}, label="nm2"),
        black_spec=AgentSpec("random"),
        budget_s=0.2,
        max_turns=100,
        seed=0,
    )
    seen = []

    result = runner.run(decision_callback=seen.append)

    check_consistent(result=result, rules=rules)
    assert result.outcome is MatchOutcome.WIN
    assert seen == result.decisions
    assert result.decisions
    assert {d.agent_label for d in result.decisions[::2]} == {"nm2"}
    assert {d.seed for d in result.decisions[1::2]} == {runner.seat_seed(Player.BLACK)}
    assert not any(d.worker_restarted for d in result.decisions)
    assert result.duration_s >= result.thinking_s(Player.WHITE)


def test_turn_cap(rules: Rules) -> None:
    runner = MatchRunner(
        rules=rules,
        white_spec=AgentSpec("random"),
        black_spec=AgentSpec("random"),
        budget_s=1.0,
        max_turns=3,
        seed=5,
    )

    result = runner.run()

    assert result.outcome is MatchOutcome.TURN_CAP
    assert result.winner is None
    assert len(result.decisions) == 6
    check_consistent(result=result, rules=rules)


def test_draw_by_turn_limit_of_rules() -> None:
    rules = Rules(max_turns=2)
    runner = MatchRunner(
        rules=rules,
        white_spec=AgentSpec("random"),
        black_spec=AgentSpec("random"),
        budget_s=1.0,
        max_turns=None,
        seed=0,
    )

    result = runner.run()

    assert result.outcome is MatchOutcome.DRAW
    assert result.winner is None
    assert len(result.decisions) == 5
    check_consistent(result=result, rules=rules)


def test_reproducible(rules: Rules) -> None:
    def moves(seed: int) -> list[Move | None]:
        runner = MatchRunner(
            rules=rules,
            white_spec=AgentSpec("random"),
            black_spec=AgentSpec("random"),
            budget_s=1.0,
            max_turns=10,
            seed=seed,
        )
        return runner.run().record.moves

    assert moves(3) == moves(3)
    assert moves(3) != moves(4)


def test_builds_each_seat_once(rules: Rules, tmp_path: Path) -> None:
    white, black = tmp_path / "white.txt", tmp_path / "black.txt"
    runner = MatchRunner(
        rules=rules,
        white_spec=AgentSpec(kind="test-counting", params={"path": str(white)}),
        black_spec=AgentSpec(kind="test-counting", params={"path": str(black)}),
        budget_s=1.0,
        max_turns=5,
        seed=0,
        preload=[TESTING_MODULE],
    )

    result = runner.run()

    assert len(result.decisions) == 10
    assert len(white.read_text().splitlines()) == 1
    assert len(black.read_text().splitlines()) == 1


def test_misbehaving_agent_still_finishes(rules: Rules) -> None:
    runner = MatchRunner(
        rules=rules,
        white_spec=AgentSpec("test-never-submits"),
        black_spec=AgentSpec("random"),
        budget_s=0.05,
        max_turns=3,
        seed=0,
        preload=[TESTING_MODULE],
    )

    result = runner.run()

    assert len(result.decisions) == 6
    assert {d.close_reason for d in result.decisions[::2]} == {"no_candidate"}
    check_consistent(result=result, rules=rules)


def test_invalid_spec_fails(rules: Rules) -> None:
    runner = MatchRunner(
        rules=rules,
        white_spec=AgentSpec("nope"),
        black_spec=AgentSpec("random"),
        budget_s=1.0,
        max_turns=1,
        seed=0,
    )

    with pytest.raises(AgentWorkerError, match="nope"):
        runner.run()


@pytest.mark.slow
def test_full_match_between_search_agents(rules: Rules) -> None:
    runner = MatchRunner(
        rules=rules,
        white_spec=AgentSpec(kind="negamax", params={"mobility": 0.1}),
        black_spec=AgentSpec("minimax"),
        budget_s=0.5,
        max_turns=40,
        seed=1,
    )

    result = runner.run()

    check_consistent(result=result, rules=rules)
    assert all(d.elapsed_s < 0.5 + 0.1 for d in result.decisions)
    assert all(d.overrun_s < 0.1 for d in result.decisions)
    assert not any(d.worker_restarted for d in result.decisions)
