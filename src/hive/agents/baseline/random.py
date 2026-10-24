import random
from typing import override

from hive.agents.base import Agent
from hive.engine.ruleset import Ruleset
from hive.engine.state import GameState, Move


class RandomAgent(Agent):
    """Agent that selects moves uniformly at random from the set of legal moves."""

    def __init__(self, ruleset: Ruleset, random_seed: int | None = None) -> None:
        """Initialize the random agent.

        Args:
            ruleset: The ruleset governing the game.
            random_seed: Optional seed for the random number generator, enabling
                reproducible move selection.
        """
        self.ruleset = ruleset
        self._rng = random.Random(random_seed)

    @override
    def choose_move(self, state: GameState) -> Move | None:
        """Select a move uniformly at random from the set of legal moves.

        Args:
            state: The current game state.

        Returns:
            A randomly selected legal move, or `None` if passing is the only option.
        """
        legal_moves = self.ruleset.get_legal_moves(state)
        return legal_moves[self._rng.randrange(len(legal_moves))]
