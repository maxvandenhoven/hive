"""Contract tests that every registered agent kind must pass."""

import pytest

from hive.agents.factory import AgentSpec, build_agent, list_agents
from hive.agents.testing import FakeClock, LocalTurnContext
from hive.engine.rules import Rules
from hive.engine.serialization import serialize_board
from hive.engine.state import GameState

_KINDS = [agent.name for agent in list_agents()]


def _snapshot(state: GameState) -> object:
    """Capture everything that defines a state, to check that it is unchanged."""
    return (
        serialize_board(state.board),
        state.current_player,
        state.current_ply,
        state.hand,
        state.queen_coord,
    )


def _ticking_turn(budget_s: float) -> LocalTurnContext:
    """Build a turn whose clock advances one millisecond every time it is read."""
    return LocalTurnContext(budget_s=budget_s, clock=FakeClock(step=0.001))


@pytest.mark.parametrize("kind", _KINDS)
def test_submits_legal_move_without_time(
    kind: str, rules: Rules, position: GameState
) -> None:
    """Test that a legal move is submitted even if the deadline has already passed."""
    agent = build_agent(AgentSpec(kind), rules, seed=0)
    turn = LocalTurnContext(budget_s=0.0)

    agent.think(position.copy(), turn)

    assert turn.submissions
    assert turn.submissions[0].move in rules.legal_moves(position)


@pytest.mark.parametrize("kind", _KINDS)
def test_respects_should_stop(kind: str, rules: Rules, position: GameState) -> None:
    """Test that unbounded thinking returns at the deadline with only legal moves."""
    agent = build_agent(AgentSpec(kind), rules, seed=0)
    turn = _ticking_turn(budget_s=0.05)

    agent.think(position.copy(), turn)

    legal_moves = rules.legal_moves(position)
    assert turn.submissions
    assert all(submission.move in legal_moves for submission in turn.submissions)
    assert not any(submission.after_stop for submission in turn.submissions)


@pytest.mark.parametrize("kind", _KINDS)
def test_stops_after_cancel(kind: str, rules: Rules, position: GameState) -> None:
    """Test that a cancelled turn still ends with a legal move."""
    agent = build_agent(AgentSpec(kind), rules, seed=0)
    turn = LocalTurnContext()
    turn.stop()

    agent.think(position.copy(), turn)

    assert turn.move in rules.legal_moves(position)


@pytest.mark.parametrize("kind", _KINDS)
def test_restores_state(kind: str, rules: Rules, position: GameState) -> None:
    """Test that thinking, interrupted or not, leaves the given state unchanged."""
    agent = build_agent(AgentSpec(kind), rules, seed=0)
    state = position.copy()
    before = _snapshot(state)

    agent.think(state, _ticking_turn(budget_s=0.05))

    assert _snapshot(state) == before


@pytest.mark.parametrize("kind", _KINDS)
def test_deterministic_for_seed(kind: str, rules: Rules, position: GameState) -> None:
    """Test that two agents with equal seeds submit the same moves over several turns."""
    runs = []
    for _ in range(2):
        agent = build_agent(AgentSpec(kind), rules, seed=7)
        turns = [_ticking_turn(budget_s=0.05) for _ in range(3)]
        for turn in turns:
            agent.think(position.copy(), turn)
        runs.append([turn.submissions for turn in turns])

    assert runs[0] == runs[1]
