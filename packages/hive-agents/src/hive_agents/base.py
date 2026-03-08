from abc import ABC, abstractmethod

from hive_engine.state import GameState, Move


class Agent(ABC):
    """Base class for all agents.

    Provides a common interface for agents that choose moves in a Hive game. Each agent
    receives a `Ruleset` at construction time, which it uses to query legal moves and
    check game termination during its search.

    Subclasses must implement `choose_move` to define their move selection strategy.
    """

    @abstractmethod
    def choose_move(self, state: GameState) -> Move | None:
        """Choose the best move for the current player.

        Parameters
        ----------
        state : GameState
            The current game state.

        Returns
        -------
        Move | None
            The chosen move, or `None` to pass the turn.
        """
