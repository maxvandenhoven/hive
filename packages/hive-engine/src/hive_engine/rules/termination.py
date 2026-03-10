from abc import ABC, abstractmethod

from typing_extensions import override

from hive_engine.state import GameState, Player


class TerminationRule(ABC):
    """Base class for termination rules that determine when the game ends.

    The `Ruleset` class holds a single `TerminationRule` instance. The methods
    `Ruleset.get_winning_players` and `Ruleset.is_finished` delegate directly to
    `get_winning_players` on the termination rule. The ruleset considers the game
    finished whenever `get_winning_players` returns a non-`None` value.

    Subclasses must implement `get_winning_players` to define the win and draw conditions
    for a given variant of Hive.
    """

    @abstractmethod
    def get_winning_players(self, state: GameState) -> list[Player] | None:
        """Determine the winning players based on the current game state.

        Parameters
        ----------
        state : GameState
            The current state of the game.

        Returns
        -------
        list[Player] | None
            A list of winning players if the game has ended, or `None` if the game is
            still in progress. A list containing both players indicates a draw.
        """


class BaseTerminationRule(TerminationRule):
    """Default termination rule for Hive.

    The game ends when at least one player's queen is completely surrounded by pieces
    (all six neighboring coordinates are occupied). The opponent of the surrounded queen's
    owner is the winner. If both queens are surrounded simultaneously, both players are
    returned as winners, indicating a draw. If neither queen has been placed or neither
    is surrounded, the game continues.
    """

    def __init__(self, max_turns_per_player: int | None = None) -> None:
        """Initialize the base termination rule.

        Parameters
        ----------
        max_turns_per_player : int | None, optional
            The maximum number of turns per player before the game is considered a draw,
            by default `None` (no turn limit).
        """
        self.max_turns_per_player = max_turns_per_player

    @override
    def get_winning_players(self, state: GameState) -> list[Player] | None:
        """Determine the winning players based on the current game state.

        Parameters
        ----------
        state : GameState
            The current state of the game.

        Returns
        -------
        list[Player] | None
            A list of winning players if the game has ended, or `None` if the game is
            still in progress. A list containing both players indicates a draw.
        """
        # The ply counts moves across all players, so the total number of allowed plies
        # is twice the max turns per player. A draw may be made in the final allowed
        # turn, so the game only ends in a draw if the ply count exceeds this total.
        if self.max_turns_per_player is not None:
            if state.current_ply > 2 * self.max_turns_per_player:
                return [Player.WHITE, Player.BLACK]

        winning_players: list[Player] = []

        for player in Player:
            queen_coord = state.get_queen_coord(player)
            if queen_coord is not None and state.is_surrounded(queen_coord):
                winning_players.append(player.opponent)

        return winning_players if winning_players else None
