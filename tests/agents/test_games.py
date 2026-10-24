import pytest

from hive.agents.base import Agent
from hive.agents.baseline.random import RandomAgent
from hive.agents.evaluators.queen_safety import QueenSafetyEvaluator
from hive.agents.search.negamax import NegamaxAgent
from hive.engine.rules import Rules
from hive.engine.state import Move, Player

# Random and greedy play can shuffle forever without surrounding a queen, so the turn
# limit ends such games in a draw.
_MAX_TURNS = 300

# Safety cap so a regression that prevents games from ending fails instead of hanging.
_MAX_PLIES = 2 * _MAX_TURNS + 2


@pytest.mark.parametrize("seed", range(3))
def test_random_vs_negamax_completes(seed: int) -> None:
    """Test that random and negamax depth 1 play a game to completion."""
    rules = Rules(max_turns=_MAX_TURNS)
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


def _random_game(seed: int, extra_calls: int) -> list[Move | None]:
    """Play a seeded random game, calling `legal_moves` extra times before every move."""
    rules = Rules(max_turns=_MAX_TURNS)
    agent = RandomAgent(rules, random_seed=seed)
    state = rules.create_initial_state()

    moves: list[Move | None] = []
    while not rules.is_finished(state):
        for _ in range(extra_calls):
            rules.legal_moves(state)
        move = agent.choose_move(state)
        state.apply_move(move)
        moves.append(move)
    return moves


@pytest.mark.parametrize("seed", range(3))
def test_seeded_random_game_reproducible(seed: int) -> None:
    """Test that a seeded game does not depend on extra `legal_moves` calls."""
    assert _random_game(seed, extra_calls=0) == _random_game(seed, extra_calls=1)
