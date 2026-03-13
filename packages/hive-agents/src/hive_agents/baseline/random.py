import random

from hive_engine.ruleset import Ruleset
from hive_engine.state import GameState, Move
from typing_extensions import override

from hive_agents.base import Agent


class RandomAgent(Agent):
    """Agent that selects moves uniformly at random from the set of legal moves."""

    def __init__(self, ruleset: Ruleset, random_seed: int | None = None) -> None:
        """Initialize the random agent.

        Parameters
        ----------
        ruleset : Ruleset
            The ruleset governing the game.
        random_seed : int | None
            Optional seed for the random number generator, enabling reproducible move
            selection.
        """
        self.ruleset = ruleset
        self._rng = random.Random(random_seed)

    @override
    def choose_move(self, state: GameState) -> Move | None:
        """Select a move uniformly at random from the set of legal moves.

        Parameters
        ----------
        state : GameState
            The current game state.

        Returns
        -------
        Move | None
            A randomly selected legal move, or `None` if passing is the only option.
        """
        legal_moves = self.ruleset.get_legal_moves(state)
        return legal_moves[self._rng.randrange(len(legal_moves))]
