import random
from typing import override

from hive.agents.base import Agent
from hive.engine.rules import Rules
from hive.engine.state import GameState, Move


class RandomAgent(Agent):
    """Agent that selects moves uniformly at random from the set of legal moves."""

    def __init__(self, rules: Rules, random_seed: int | None = None) -> None:
        """Initialize the random agent.

        Args:
            rules: The rules governing the game.
            random_seed: Optional seed for the random number generator, enabling
                reproducible move selection.
        """
        self.rules = rules
        self._rng = random.Random(random_seed)

    @override
    def choose_move(self, state: GameState) -> Move | None:
        """Select a move uniformly at random from the set of legal moves.

        Args:
            state: The current game state.

        Returns:
            A randomly selected legal move, or `None` if passing is the only option.
        """
        legal_moves = self.rules.legal_moves(state)
        return legal_moves[self._rng.randrange(len(legal_moves))]
