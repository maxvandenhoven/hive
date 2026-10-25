import pytest

from hive.agents.random import RandomAgent
from hive.agents.testing import LocalTurnContext
from hive.engine.rules import Rules
from hive.engine.state import GameState


def _random_position(rules: Rules, seed: int, plies: int) -> GameState:
    """Play a seeded random game for a number of plies, or until it finishes."""
    agent = RandomAgent(rules, seed=seed)
    state = rules.create_initial_state()

    for _ in range(plies):
        if rules.is_finished(state):
            break

        state.apply_move(LocalTurnContext().run(agent, state))

    return state


@pytest.fixture(scope="function")
def rules() -> Rules:
    """Build the default rules."""
    return Rules()


@pytest.fixture(scope="function", params=[0, 6, 14, 24], ids=lambda p: f"ply{p}")
def position(request: pytest.FixtureRequest, rules: Rules) -> GameState:
    """Build the start position and a few unfinished positions from seeded random play."""
    state = _random_position(rules, seed=request.param, plies=request.param)
    assert not rules.is_finished(state)

    return state
