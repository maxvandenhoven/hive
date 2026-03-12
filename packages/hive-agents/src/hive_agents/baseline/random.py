import random

from hive_engine.ruleset import Ruleset
from hive_engine.state import GameState, Move
from typing_extensions import override

from hive_agents.base import Agent


class RandomAgent(Agent):
    """Agent that selects moves uniformly at random from the set of legal moves."""

    def __init__(self, ruleset: Ruleset) -> None:
        """Initialize the random agent.

        Parameters
        ----------
        ruleset : Ruleset
            The ruleset governing the game.
        """
        self.ruleset = ruleset

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
        return legal_moves[random.randrange(len(legal_moves))]
