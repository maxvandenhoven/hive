import pytest

from hive.agents.base import Agent
from hive.agents.baseline.random import RandomAgent
from hive.agents.evaluators.queen_safety import QueenSafetyEvaluator
from hive.agents.search.negamax import NegamaxAgent
from hive.engine.rules import Rules
from hive.engine.state import Player

# Safety cap so a regression that prevents games from ending fails instead of hanging.
_MAX_PLIES = 2000


@pytest.mark.parametrize("seed", range(3))
def test_random_vs_negamax_completes(seed: int) -> None:
    """Test that random and negamax depth 1 play a game to completion."""
    rules = Rules()
    agents: dict[Player, Agent] = {
        Player.WHITE: RandomAgent(rules, random_seed=seed),
        Player.BLACK: NegamaxAgent(rules, QueenSafetyEvaluator(), depth=1),
    }
    state = rules.create_initial_state()

    while not rules.is_finished(state) and state.current_ply < _MAX_PLIES:
        move = agents[state.current_player].choose_move(state)
        assert move in rules.legal_moves(state)
        state.apply_move(move)

    assert rules.is_finished(state)
    assert rules.winners(state)
