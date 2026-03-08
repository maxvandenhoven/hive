from abc import ABC, abstractmethod

from typing_extensions import override

from hive_engine.grid import Coordinate
from hive_engine.state import GameState, PieceType


class BaseMobilityRule(ABC):
    """Base class for mobility rules that determine which pieces may move.

    The `Ruleset` class holds a single `BaseMobilityRule` instance. When generating legal
    movement moves via `Ruleset.get_legal_movement_moves`, the ruleset calls
    `get_movable_pieces` to obtain the list of pieces that are eligible to move. Each
    returned coordinate and piece type is then passed to the corresponding
    `BaseMovementRule` to determine the specific target coordinates.

    Subclasses must implement `get_movable_pieces` to define the criteria under which a
    piece on the board is allowed to move.
    """

    @abstractmethod
    def get_movable_pieces(self, state: GameState) -> list[tuple[Coordinate, PieceType]]:
        """Get all pieces on the board that are allowed to move.

        Parameters
        ----------
        state : GameState
            The current state of the game.

        Returns
        -------
        list[tuple[Coordinate, PieceType]]
            A list of tuples, each containing the axial coordinate `(q, r)` of a movable
            piece and its `PieceType`.
        """


class DefaultMobilityRule(BaseMobilityRule):
    """Default mobility rule for Hive.

    A piece belonging to the current player may move if all of the following conditions
    are met: the current player's queen has been placed (unless
    `can_move_before_queen_placed` is `True`), the piece is the top piece on its
    coordinate (i.e., it is not covered by a beetle), and removing the piece does not
    break the hive into disconnected components (the one-hive rule).
    """

    def __init__(self, can_move_before_queen_placed: bool = False) -> None:
        """Initialize the default mobility rule.

        Parameters
        ----------
        can_move_before_queen_placed : bool, optional
            Whether pieces can be moved before the queen is placed. Defaults to `False`.
        """
        self.can_move_before_queen_placed = can_move_before_queen_placed

    @override
    def get_movable_pieces(self, state: GameState) -> list[tuple[Coordinate, PieceType]]:
        """Get all pieces on the board that are allowed to move.

        Parameters
        ----------
        state : GameState
            The current state of the game.

        Returns
        -------
        list[tuple[Coordinate, PieceType]]
            A list of tuples, each containing the axial coordinate `(q, r)` of a movable
            piece and its `PieceType`.
        """
        if (
            not self.can_move_before_queen_placed
            and state.get_queen_coord(state.current_player) is None
        ):
            return []

        movable_pieces: list[tuple[Coordinate, PieceType]] = []

        for coord in state.get_occupied_coords():
            top_piece = state.get_top_piece(coord)

            if top_piece.owner != state.current_player:
                continue

            if not state.is_connected_after_removing(coord):
                continue

            movable_pieces.append((coord, top_piece.type))

        return movable_pieces
