from abc import ABC, abstractmethod

from hive_engine.grid import Coordinate, get_neighbors
from hive_engine.state import GameState, PieceType


class PlacementRule(ABC):
    """Base class for placement rules that govern where and which pieces may be placed.

    The `Ruleset` class holds a single `PlacementRule` instance. When generating
    legal placement moves via `Ruleset.get_legal_placement_moves`, the ruleset calls
    `get_placeable_coords` to obtain valid board positions and `get_placeable_piece_types`
    to obtain the piece types available for placement. The Cartesian product of these two
    results forms the full set of legal placement moves.

    Subclasses must implement both methods to define the placement constraints for a
    given variant of Hive.
    """

    @abstractmethod
    def get_placeable_coords(self, state: GameState) -> list[Coordinate]:
        """Get all coordinates where a piece may be placed from the hand.

        Parameters
        ----------
        state : GameState
            The current state of the game.

        Returns
        -------
        list[Coordinate]
            All axial coordinates `(q, r)` where a piece may be placed.
        """

    @abstractmethod
    def get_placeable_piece_types(self, state: GameState) -> list[PieceType]:
        """Get all piece types that the current player may place.

        Parameters
        ----------
        state : GameState
            The current state of the game.

        Returns
        -------
        list[PieceType]
            All piece types that the current player has in hand and is allowed to place.
        """


class BasePlacementRule(PlacementRule):
    """Default placement rule for Hive.

    On the very first turn of the game (ply 0), the first player places a piece at the
    origin `(0, 0)`. On the second turn (ply 1), the second player places a piece on any
    coordinate neighboring the origin. On all subsequent turns, a piece may only be
    placed on an unoccupied coordinate that is adjacent to at least one of the current
    player's pieces and not adjacent to any of the opponent's pieces.

    If `place_queen_on_turn` is set, the current player is forced to place their queen if
    they have not done so by the specified turn number. Otherwise, any piece type
    remaining in the player's hand may be placed.
    """

    def __init__(self, place_queen_on_turn: int | None = 4) -> None:
        """Initialize the default placement rule.

        Parameters
        ----------
        place_queen_on_turn : int | None, optional
            The turn number (one-indexed, per player) by which the queen must be placed.
            Defaults to `4`. If `None`, no deadline is enforced.
        """
        self.place_queen_on_turn = place_queen_on_turn

    def get_placeable_coords(self, state: GameState) -> list[Coordinate]:
        """Get all coordinates where a piece may be placed from the hand.

        Parameters
        ----------
        state : GameState
            The current state of the game.

        Returns
        -------
        list[Coordinate]
            All axial coordinates `(q, r)` where a piece may be placed.
        """
        if state.current_ply == 0:
            return [(0, 0)]

        if state.current_ply == 1:
            return get_neighbors((0, 0))

        placeable_coords = set()
        for coord in state.get_occupied_coords():
            top_piece = state.get_top_piece(coord)
            if top_piece.owner != state.current_player:
                continue

            for neighbor in get_neighbors(coord):
                if state.is_occupied(neighbor):
                    continue

                if state.get_adjacent_players(neighbor) == {state.current_player}:
                    placeable_coords.add(neighbor)

        return list(placeable_coords)

    def get_placeable_piece_types(self, state: GameState) -> list[PieceType]:
        """Get all piece types that the current player may place.

        Parameters
        ----------
        state : GameState
            The current state of the game.

        Returns
        -------
        list[PieceType]
            All piece types that the current player has in hand and is allowed to place.
        """
        if self.place_queen_on_turn is not None:
            player_ply = state.current_ply // 2
            queen_placed = state.get_queen_coord(state.current_player) is not None
            if player_ply + 1 >= self.place_queen_on_turn and not queen_placed:
                return [PieceType.QUEEN]

        return [
            piece_type
            for piece_type, count in state.hand[state.current_player].items()
            if count > 0
        ]
