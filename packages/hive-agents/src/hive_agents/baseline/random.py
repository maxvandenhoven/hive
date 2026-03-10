import random

from hive_engine.ruleset import Ruleset
from hive_engine.state import GameState, Move
from typing_extensions import override

from hive_agents.base import Agent


class RandomAgent(Agent):
    """Agent that selects moves uniformly at random from the set of legal moves."""

    def __init__(self, ruleset: Ruleset, exclude_pass: bool = True) -> None:
        """Initialize the random agent.

        Parameters
        ----------
        ruleset : Ruleset
            The ruleset governing the game.
        exclude_pass : bool, optional
            Whether to exlucde passing from the set of legal moves if possible, by
            default `True`. If passing is the only legal move, it will still be selected.
        """
        self.ruleset = ruleset
        self.exclude_pass = exclude_pass

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
            A randomly selected legal move, or `None` if there are no legal moves.
        """
        legal_moves = set(self.ruleset.get_legal_moves(state))

        if len(legal_moves) >= 2 and self.exclude_pass:
            legal_moves.discard(None)

        return random.choice(list(legal_moves))
