from abc import ABC, abstractmethod

from typing_extensions import override

from hive_engine.grid import HEX_DIRECTIONS, Coordinate, add
from hive_engine.state import GameState


class MovementRule(ABC):
    """Base class for movement rules that govern how a piece type moves on the board.

    The `Ruleset` class maps each `PieceType` to exactly one `MovementRule` instance
    via the `movement_rules` dictionary. When generating legal movement moves,
    `Ruleset.get_legal_movement_moves` iterates over all movable pieces (as determined by
    the mobility rule) and calls `get_target_coords` on the corresponding movement rule
    to obtain the set of coordinates that piece can reach.

    Subclasses must implement `get_target_coords` to define the movement behavior for a
    specific piece type.
    """

    @abstractmethod
    def get_target_coords(self, state: GameState, coord: Coordinate) -> list[Coordinate]:
        """Get all coordinates a piece can move to, assuming it is allowed to move.

        Parameters
        ----------
        state : GameState
            The current state of the game.
        coord : Coordinate
            The current axial coordinate `(q, r)` of the piece to move.

        Returns
        -------
        list[Coordinate]
            All possible axial coordinates `(q', r')` the piece can move to.
        """


class BaseSlidingMovementRule(MovementRule):
    """Base class for piece types that slide along the hive surface.

    Sliding pieces move by shifting into an unoccupied neighboring coordinate while
    remaining in contact with at least one other piece. A slide is only valid if the
    piece is not physically blocked by two occupied flanking coordinates (the gate rule)
    and if the destination has at least one occupied neighbor to maintain hive contact.

    Subclasses inherit `get_slideable_neighbors`, which encapsulates this shared sliding
    logic, and use it within their `get_target_coords` implementations.
    """

    def get_slideable_neighbors(
        self, state: GameState, coord: Coordinate
    ) -> list[Coordinate]:
        """Get the neighboring coordinates that a piece can slide into.

        A neighbor is slideable if it is unoccupied, not blocked by the gate rule (both
        flanking coordinates occupied), and has at least one occupied neighbor of its own
        to maintain hive contact.

        Parameters
        ----------
        state : GameState
            The current state of the game.
        coord : Coordinate
            The axial coordinate `(q, r)` to slide from.

        Returns
        -------
        list[Coordinate]
            The neighboring coordinates that satisfy all sliding constraints.
        """
        slideable_neighbors: list[Coordinate] = []
        for neighbor_coord in state.get_neighbors(coord):
            if state.is_occupied(neighbor_coord):
                continue

            if not state.can_slide(source_coord=coord, target_coord=neighbor_coord):
                continue

            if not any(
                state.is_occupied(other_neighbor_coord)
                for other_neighbor_coord in state.get_neighbors(neighbor_coord)
            ):
                continue

            slideable_neighbors.append(neighbor_coord)

        return slideable_neighbors


class BaseQueenMovementRule(BaseSlidingMovementRule):
    """Default movement rule for queen pieces.

    The queen moves by sliding exactly one space along the hive surface. It can only
    slide into an unoccupied neighboring coordinate that is not blocked by the gate rule
    and that maintains contact with the hive. The piece is temporarily lifted from the
    board before computing slideable neighbors to avoid self-obstruction.
    """

    @override
    def get_target_coords(self, state: GameState, coord: Coordinate) -> list[Coordinate]:
        """Get all coordinates a piece can move to, assuming it is allowed to move.

        Parameters
        ----------
        state : GameState
            The current state of the game.
        coord : Coordinate
            The current axial coordinate `(q, r)` of the piece to move.

        Returns
        -------
        list[Coordinate]
            All possible axial coordinates `(q', r')` the piece can move to.
        """
        with state.piece_lifted(coord):
            return self.get_slideable_neighbors(state, coord)


class BaseBeetleMovementRule(BaseSlidingMovementRule):
    """Default movement rule for beetle pieces.

    The beetle can either slide one space along the hive surface like the queen, or climb
    on top of an adjacent occupied coordinate. When on top of the hive, the beetle covers
    the piece beneath it. Both slideable (unoccupied) and climbable (occupied) neighbors
    are valid destinations. The piece is temporarily lifted before computing destinations
    to avoid self-obstruction.
    """

    @override
    def get_target_coords(self, state: GameState, coord: Coordinate) -> list[Coordinate]:
        """Get all coordinates a piece can move to, assuming it is allowed to move.

        Parameters
        ----------
        state : GameState
            The current state of the game.
        coord : Coordinate
            The current axial coordinate `(q, r)` of the piece to move.

        Returns
        -------
        list[Coordinate]
            All possible axial coordinates `(q', r')` the piece can move to.
        """
        with state.piece_lifted(coord):
            slideable_destinations = self.get_slideable_neighbors(state, coord)

            climbable_destinations: list[Coordinate] = []
            for neighbor_coord in state.get_neighbors(coord):
                if state.is_occupied(neighbor_coord):
                    climbable_destinations.append(neighbor_coord)

        return slideable_destinations + climbable_destinations


class BaseGrasshopperMovementRule(MovementRule):
    """Default movement rule for grasshopper pieces.

    The grasshopper moves by jumping in a straight line over one or more occupied
    coordinates. It must jump over at least one piece and lands on the first unoccupied
    coordinate in that direction. The grasshopper checks each of the six hex directions
    independently.
    """

    @override
    def get_target_coords(self, state: GameState, coord: Coordinate) -> list[Coordinate]:
        """Get all coordinates a piece can move to, assuming it is allowed to move.

        Parameters
        ----------
        state : GameState
            The current state of the game.
        coord : Coordinate
            The current axial coordinate `(q, r)` of the piece to move.

        Returns
        -------
        list[Coordinate]
            All possible axial coordinates `(q', r')` the piece can move to.
        """
        destinations = []

        for direction in HEX_DIRECTIONS:
            current_coord = add(coord, direction)
            if not state.is_occupied(current_coord):
                continue

            while state.is_occupied(current_coord):
                current_coord = add(current_coord, direction)

            destinations.append(current_coord)

        return destinations


class BaseSpiderMovementRule(BaseSlidingMovementRule):
    """Default movement rule for spider pieces.

    The spider moves by sliding exactly three spaces along the hive surface. It must take
    exactly three steps, each of which must be a valid slide, and it cannot revisit any
    coordinate during its path. A depth-first search explores all paths of length three
    from the spider's starting position. The piece is temporarily lifted before computing
    destinations to avoid self-obstruction.
    """

    @override
    def get_target_coords(self, state: GameState, coord: Coordinate) -> list[Coordinate]:
        """Get all coordinates a piece can move to, assuming it is allowed to move.

        Parameters
        ----------
        state : GameState
            The current state of the game.
        coord : Coordinate
            The current axial coordinate `(q, r)` of the piece to move.

        Returns
        -------
        list[Coordinate]
            All possible axial coordinates `(q', r')` the piece can move to.
        """
        destinations = set()

        def _dfs(
            current_coord: Coordinate, visited_coords: set[Coordinate], depth: int
        ) -> None:
            if depth == 3:
                destinations.add(current_coord)
                return

            for neighbor_coord in self.get_slideable_neighbors(state, current_coord):
                if neighbor_coord in visited_coords:
                    continue

                visited_coords.add(neighbor_coord)
                _dfs(
                    current_coord=neighbor_coord,
                    visited_coords=visited_coords,
                    depth=depth + 1,
                )
                visited_coords.remove(neighbor_coord)

        with state.piece_lifted(coord):
            _dfs(current_coord=coord, visited_coords={coord}, depth=0)

        destinations.discard(coord)

        return list(destinations)


class BaseAntMovementRule(BaseSlidingMovementRule):
    """Default movement rule for ant pieces.

    The ant moves by sliding any number of spaces along the hive surface. It can reach
    any unoccupied coordinate that is connected to its starting position through a chain
    of valid slides. A breadth-first search explores all reachable coordinates. The piece
    is temporarily lifted before computing destinations to avoid self-obstruction.
    """

    @override
    def get_target_coords(self, state: GameState, coord: Coordinate) -> list[Coordinate]:
        """Get all coordinates a piece can move to, assuming it is allowed to move.

        Parameters
        ----------
        state : GameState
            The current state of the game.
        coord : Coordinate
            The current axial coordinate `(q, r)` of the piece to move.

        Returns
        -------
        list[Coordinate]
            All possible axial coordinates `(q', r')` the piece can move to.
        """
        destinations = set()

        visited_coords = {coord}
        frontier = [coord]

        with state.piece_lifted(coord):
            while frontier:
                current_coord = frontier.pop()
                for neighbor_coord in self.get_slideable_neighbors(state, current_coord):
                    if neighbor_coord in visited_coords:
                        continue

                    destinations.add(neighbor_coord)
                    visited_coords.add(neighbor_coord)
                    frontier.append(neighbor_coord)

        destinations.discard(coord)

        return list(destinations)
