from collections.abc import Generator, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated

from pydantic import Field, PlainSerializer, PlainValidator

from hive.engine.codec import JsonCodec, NamedIntEnum, json_adapter
from hive.engine.grid import Coordinate, get_flanking_coords, get_neighbors


class Player(NamedIntEnum):
    """An enumeration of the two players in a Hive game."""

    WHITE = 0
    BLACK = 1

    @property
    def opponent(self) -> "Player":
        """Get the opponent of a player.

        Returns:
            The other player. `BLACK` if the current player is `WHITE`, and `WHITE` if the
            current player is `BLACK`.
        """
        return Player.BLACK if self is Player.WHITE else Player.WHITE


class PieceType(NamedIntEnum):
    """An enumeration of the available piece types."""

    QUEEN = 0
    BEETLE = 1
    GRASSHOPPER = 2
    SPIDER = 3
    ANT = 4


@dataclass(frozen=True, slots=True)
class Piece(JsonCodec):
    """A game piece with a type and an owner.

    Pieces are immutable, so boards can share them and copying a board only needs to copy
    its stacks. The JSON form is `{"piece": "ant", "owner": "white"}`.

    Attributes:
        type: The type of the piece.
        owner: The player that owns the piece.
    """

    type: Annotated[PieceType, Field(alias="piece")]
    owner: Player


SHARED_PIECES: Mapping[tuple[Player, PieceType], Piece] = {
    (owner, piece_type): Piece(type=piece_type, owner=owner)
    for owner in Player
    for piece_type in PieceType
}
"""One instance of every piece by owner and type, which placements put on the board.

Pieces are immutable and compared by value, so sharing them is safe, and looking one up
is cheaper than creating it on every placement.
"""


@dataclass(slots=True)
class Move(JsonCodec):
    """A game move that places or moves a piece on the board.

    A move with `source_coord` set to `None` represents a placement from the player's
    hand. A move with a `source_coord` represents a movement of an existing piece on the
    board. The JSON form is `{"piece": "ant", "from": [q, r] | null, "to": [q, r]}`, and a
    pass (`None` where a move is expected) is `null`.

    Attributes:
        piece_type: The type of piece being placed or moved.
        source_coord: The axial coordinate `(q, r)` the piece moves from, or `None` if the
            piece is being placed from the hand.
        target_coord: The axial coordinate `(q', r')` the piece moves or is placed to.
    """

    piece_type: Annotated[PieceType, Field(alias="piece")]
    source_coord: Annotated[Coordinate | None, Field(alias="from")]
    target_coord: Annotated[Coordinate, Field(alias="to")]

    def __str__(self) -> str:
        """Describe the move for messages, for example `move ant from (0, 0) to (1, 0)`.

        Returns:
            The description of the placement or movement.
        """
        piece_name = self.piece_type.name.lower()

        if self.source_coord is None:
            return f"place {piece_name} at {self.target_coord}"

        return f"move {piece_name} from {self.source_coord} to {self.target_coord}"


@dataclass(frozen=True, slots=True)
class BoardCell(JsonCodec):
    """One occupied cell of a board in the JSON form of `GameBoard`.

    Attributes:
        coord: The coordinate of the cell.
        stack: The pieces on the cell, ordered bottom to top.
    """

    coord: Coordinate
    stack: list[Piece]

    @classmethod
    def split_board(cls, board: "GameBoard") -> list["BoardCell"]:
        """Split a board into its occupied cells.

        Args:
            board: The board.

        Returns:
            One cell per occupied coordinate, ordered by coordinate.
        """
        return [cls(coord=coord, stack=board[coord]) for coord in sorted(board)]

    @classmethod
    def join_board(cls, data: object) -> "GameBoard":
        """Read a board from the JSON form of its cells.

        Args:
            data: A list of `{"coord": [q, r], "stack": [...]}` objects.

        Returns:
            The board.

        Raises:
            ValueError: If `data` is not a list of cells, or a coordinate appears more
                than once.
        """
        cells: list[BoardCell] = json_adapter(list[BoardCell]).validate_python(data)
        board = {cell.coord: cell.stack for cell in cells}

        if len(board) != len(cells):
            msg = "The board has more than one cell at the same coordinate."
            raise ValueError(msg)

        return board


type GameBoard = Annotated[
    dict[Coordinate, list[Piece]],
    PlainValidator(BoardCell.join_board, json_schema_input_type=list[BoardCell]),
    PlainSerializer(BoardCell.split_board, return_type=list[BoardCell]),
]
"""A mapping from axial coordinates to stacks of pieces on the game board.

Each key is an occupied coordinate and the corresponding value is the list of pieces
stacked on that coordinate, ordered from bottom to top. An empty stack is never stored.
When the last piece is removed from a coordinate, the entry should be deleted. The JSON
form is a list of `BoardCell`s ordered by coordinate, since JSON keys cannot be
coordinates; the annotations only affect conversion.
"""


class GameState:
    """The complete state of a Hive game at a given point in time.

    Tracks the board layout, current player, ply count, queen positions, each player's
    hand, and which piece types have been placed. Provides utility methods for querying
    and manipulating the board.
    """

    def __init__(
        self,
        piece_type_count: Mapping[PieceType, int],
        starting_player: Player = Player.WHITE,
    ) -> None:
        """Initialize a new game state.

        Args:
            piece_type_count: A mapping from each piece type to the number of copies each
                player receives at the start of the game.
            starting_player: The player who takes the first turn. Defaults to
                `Player.WHITE`.
        """
        self.board: GameBoard = {}
        self.current_player = starting_player
        self.current_ply = 0

        self.hand: dict[Player, dict[PieceType, int]] = {
            Player.WHITE: dict(piece_type_count),
            Player.BLACK: dict(piece_type_count),
        }

        self.queen_coord: dict[Player, Coordinate | None] = {
            Player.WHITE: None,
            Player.BLACK: None,
        }

    def copy(self) -> "GameState":
        """Copy the state, so moves applied to the copy do not affect the original.

        Pieces are immutable, so only the stacks and the per-player mappings are copied.

        Returns:
            A state with the same board, player, ply, hands and queen coordinates.
        """
        state = GameState(piece_type_count={}, starting_player=self.current_player)
        state.board = {coord: list(stack) for coord, stack in self.board.items()}
        state.current_ply = self.current_ply
        state.hand = {player: dict(hand) for player, hand in self.hand.items()}
        state.queen_coord = dict(self.queen_coord)

        return state

    def calculate_boundary_coords(self) -> set[Coordinate]:
        """Determine which unoccupied coordinates have at least one occupied neighbor.

        This method is only used for internal testing purposes and is not optimized for
        efficiency, as the boundary is iteratively updated on every move during normal
        play.

        Returns:
            The set of unoccupied coordinates that have at least one occupied neighbor.
        """
        # Collect all coordinates that neighbor an occupied coordinate on the board, but
        # are not themselves occupied.
        boundary_coords: set[Coordinate] = set()
        occupied_coords = self.get_occupied_coords()

        for occupied_coord in occupied_coords:
            neighbor_coords = get_neighbors(occupied_coord)

            for neighbor_coord in neighbor_coords:
                if not self.is_occupied(neighbor_coord):
                    boundary_coords.add(neighbor_coord)

        return boundary_coords

    @contextmanager
    def piece_lifted(self, coord: Coordinate) -> Generator[Piece]:
        """Temporarily lift the top piece from a coordinate.

        Args:
            coord: The axial coordinate `(q, r)` to lift the top piece from.

        Yields:
            The lifted piece, which is put back on top of the coordinate afterwards.

        Raises:
            ValueError: If there is no piece at the coordinate.
        """
        try:
            lifted_piece = self.board[coord].pop()
        except IndexError as e:
            msg = f"Cannot lift top piece from empty coordinate `{coord}`."
            raise ValueError(msg) from e

        lifted_final_piece = False

        if len(self.board[coord]) == 0:
            del self.board[coord]
            lifted_final_piece = True

        try:
            yield lifted_piece
        finally:
            if lifted_final_piece:
                self.board[coord] = []

            self.board[coord].append(lifted_piece)

    def is_surrounded(self, coord: Coordinate) -> bool:
        """Check whether a coordinate is surrounded by other pieces.

        Args:
            coord: The axial coordinate `(q, r)` to check.

        Returns:
            True if the coordinate to check has six occupied neighbors, otherwise False.
        """
        # This runs for both queens at every node of a search, and most queens have a
        # free neighbor, so the check stops at the first one.
        board = self.board

        for neighbor_coord in get_neighbors(coord):
            if neighbor_coord not in board:
                return False

        return True

    def count_occupied_neighbors(self, coord: Coordinate) -> int:
        """Count the occupied coordinates that directly neighbor a coordinate.

        Args:
            coord: The axial coordinate `(q, r)` to check.

        Returns:
            The number of occupied neighbors, from zero to six.
        """
        board = self.board
        count = 0

        for neighbor_coord in get_neighbors(coord):
            if neighbor_coord in board:
                count += 1

        return count

    def is_occupied(self, coord: Coordinate) -> bool:
        """Check if a coordinate on the game board is occupied (has a piece) or not.

        Args:
            coord: The axial coordinate `(q, r)` to check.

        Returns:
            True if there is a piece on the given coordinate, otherwise False.
        """
        return coord in self.board

    def get_queen_coord(self, player: Player) -> Coordinate | None:
        """Get the coordinate of the player's queen piece.

        Args:
            player: The player to get the queen coordinate for.

        Returns:
            The axial coordinate `(q, r)` of the player's queen piece, or None if the
            queen has not been placed on the board yet.
        """
        return self.queen_coord[player]

    def get_top_piece(self, coord: Coordinate) -> Piece:
        """Get the top piece that is on an occupied coordinate.

        Args:
            coord: The axial coordinate `(q, r)` to check.

        Returns:
            The top-most piece that is occupying the given coordinate.
        """
        return self.board[coord][-1]

    def get_stack_height(self, coord: Coordinate) -> int:
        """Get the height of the stack on a coordinate.

        Args:
            coord: The axial coordinate `(q, r)` to check.

        Returns:
            The height of the stack, or zero if the coordinate is unoccupied.
        """
        stack = self.board.get(coord)
        return len(stack) if stack is not None else 0

    def get_occupied_coords(self) -> set[Coordinate]:
        """Get all occupied coordinates on the board.

        Return the occupied coordinates as a set for fast membership checks and removal.

        Returns:
            The axial coordinates `(q, r)` that have at least one piece on the board.
        """
        return set(self.board.keys())

    def get_articulation_points(self) -> set[Coordinate]:
        """Find all coordinates whose removal would disconnect the board.

        Uses Tarjan's articulation point algorithm to identify articulation points in
        linear time. A coordinate is an articulation point if removing it would split the
        remaining occupied coordinates into two or more disconnected components.
        Coordinates with a stack height greater than one are excluded, as removing the top
        piece still leaves the coordinate occupied.

        Returns:
            The set of coordinates whose removal would disconnect the board.
        """
        occupied_coords = self.get_occupied_coords()

        # A board with two or fewer pieces can never be disconnected by # removing a
        # single piece.
        if len(occupied_coords) <= 2:
            return set()

        # Tarjan's articulation point algorithm using an iterative DFS. Each coordinate is
        # assigned a discovery time and a low value. The low value tracks the earliest
        # discovered coordinate reachable from the subtree.
        discovery_times: dict[Coordinate, int] = {}
        low_values: dict[Coordinate, int] = {}
        parent_coords: dict[Coordinate, Coordinate | None] = {}
        child_counts: dict[Coordinate, int] = {}
        articulation_coords: set[Coordinate] = set()

        start_coord: Coordinate = next(iter(occupied_coords))
        time_counter = 0

        discovery_times[start_coord] = time_counter
        low_values[start_coord] = time_counter
        parent_coords[start_coord] = None
        child_counts[start_coord] = 0
        time_counter += 1

        # Maintain a per-coordinate neighbor iterator so that the DFS can resume
        # processing neighbors after returning from a simulated recursive call.
        neighbor_iters: dict[Coordinate, Iterator[Coordinate]] = {
            start_coord: iter(get_neighbors(start_coord))
        }
        stack: list[Coordinate] = [start_coord]

        while stack:
            current_coord = stack[-1]
            advanced = False

            for neighbor_coord in neighbor_iters[current_coord]:
                if neighbor_coord not in occupied_coords:
                    continue

                # Tree edge: visit the unvisited neighbor.
                if neighbor_coord not in discovery_times:
                    parent_coords[neighbor_coord] = current_coord
                    discovery_times[neighbor_coord] = time_counter
                    low_values[neighbor_coord] = time_counter
                    child_counts[neighbor_coord] = 0
                    time_counter += 1

                    neighbor_iters[neighbor_coord] = iter(get_neighbors(neighbor_coord))
                    stack.append(neighbor_coord)
                    advanced = True

                    break

                # Back edge: update the low value.
                if neighbor_coord != parent_coords[current_coord]:
                    low_values[current_coord] = min(
                        low_values[current_coord], discovery_times[neighbor_coord]
                    )

            # All neighbors have been processed; backtrack.
            if not advanced:
                stack.pop()

                if stack:
                    parent_coord = stack[-1]
                    low_values[parent_coord] = min(
                        low_values[parent_coord], low_values[current_coord]
                    )
                    child_counts[parent_coord] += 1

                    # Root of the DFS tree: articulation point if it has two or more
                    # children in the DFS tree.
                    if parent_coords[parent_coord] is None:
                        if child_counts[parent_coord] >= 2:
                            articulation_coords.add(parent_coord)

                    # Non-root: articulation point if no vertex in the subtree rooted at
                    # the child can reach an ancestor of the parent.
                    else:
                        if low_values[current_coord] >= discovery_times[parent_coord]:
                            articulation_coords.add(parent_coord)

        # Coordinates with multiple stacked pieces remain occupied after removing the top
        # piece, so they cannot disconnect the board.
        return {
            coord for coord in articulation_coords if self.get_stack_height(coord) == 1
        }

    def is_connected(self) -> bool:
        """Check if all occupied coordinates on the board form one connected group.

        Returns:
            True if every occupied coordinate can be reached from every other one by
            moving between direct neighbors, or if the board is empty.
        """
        occupied_coords = self.get_occupied_coords()

        if not occupied_coords:
            return True

        start_coord: Coordinate = next(iter(occupied_coords))
        seen: set[Coordinate] = {start_coord}
        stack: list[Coordinate] = [start_coord]

        while stack:
            candidate_coord = stack.pop()

            for neighbor_coord in get_neighbors(candidate_coord):
                if neighbor_coord in occupied_coords and neighbor_coord not in seen:
                    seen.add(neighbor_coord)
                    stack.append(neighbor_coord)

        return len(seen) == len(occupied_coords)

    def is_connected_after_removing(self, coord: Coordinate) -> bool:
        """Check if the game board remains connected after removing a piece.

        This method uses depth-first search to verify that all occupied coordinates on the
        board are connected, i.e., can be reached by moving between direct neighbors.

        Args:
            coord: The axial coordinate `(q, r)` to remove.

        Returns:
            True if the board remains connected after removing the top piece from the
            given coordinate.
        """
        # The hive always remains connected if there are more than one pieces on the given
        # coordinate.
        if self.get_stack_height(coord) > 1:
            return True

        # Get the occupied coordinates on the board and remove the given coordinate, as it
        # will not be present after removal.
        occupied_coords = self.get_occupied_coords()
        occupied_coords.remove(coord)

        # Consider the game board as a graph, where coordinates are connected if they are
        # direct neighbors. Use depth-first search to traverse the graph and verify that
        # all occupied coordinates can be found (except for the given coordinate).
        start_coord: Coordinate = next(iter(occupied_coords))
        seen: set[Coordinate] = {start_coord}
        stack: list[Coordinate] = [start_coord]

        while stack:
            candidate_coord = stack.pop()

            for neighbor_coord in get_neighbors(candidate_coord):
                if neighbor_coord in occupied_coords and neighbor_coord not in seen:
                    seen.add(neighbor_coord)
                    stack.append(neighbor_coord)

        return len(seen) == len(occupied_coords)

    def can_slide(self, source_coord: Coordinate, target_coord: Coordinate) -> bool:
        """Check if a piece can move to a neighbor without being blocked by other pieces.

        Args:
            source_coord: The axial coordinate `(q, r)` from which the pieces moves.
            target_coord: The axial coordinate `(q', r')` that the piece moves into.

        Returns:
            True if the piece is not blocked by adjacent pieces, otherwise False.
        """
        # The piece cannot move if the target coordinate occupied.
        if self.is_occupied(target_coord):
            return False

        # The two coordinates flanking the source and target coordinates should not both
        # be occupied.
        anti_clockwise_coord, clockwise_coord = get_flanking_coords(
            source_coord=source_coord, target_coord=target_coord
        )

        return not (
            self.is_occupied(anti_clockwise_coord) and self.is_occupied(clockwise_coord)
        )

    def get_adjacent_players(self, coord: Coordinate) -> set[Player]:
        """Check which players own pieces adjacent to the given coordinate.

        Args:
            coord: The axial coordinate `(q, r)` to check.

        Returns:
            The players that own pieces directly neighboring the given coordinate.
        """
        owners: set[Player] = set()

        for neighbor_coord in get_neighbors(coord):
            if self.is_occupied(neighbor_coord):
                top_piece = self.get_top_piece(neighbor_coord)
                owners.add(top_piece.owner)

        return owners

    def apply_placement(self, move: Move) -> None:
        """Apply a placement move to the game state.

        Removes the piece from the current player's hand and places it on the board at the
        target coordinate. If the placed piece is a queen, the queen coordinate for the
        current player is updated.

        Args:
            move: The placement move to apply. The `source_coord` must be `None`.
        """
        piece = SHARED_PIECES[self.current_player, move.piece_type]
        self.hand[self.current_player][move.piece_type] -= 1

        self.board.setdefault(move.target_coord, []).append(piece)

        if move.piece_type is PieceType.QUEEN:
            self.queen_coord[self.current_player] = move.target_coord

    def undo_placement(self, move: Move) -> None:
        """Undo a previously applied placement move.

        Removes the piece from the board at the target coordinate and returns it to the
        current player's hand. If the piece is a queen, the queen coordinate for the
        current player is reset to `None`.

        Args:
            move: The placement move to undo. The `source_coord` must be `None`.
        """
        self.board[move.target_coord].pop()

        if not self.board[move.target_coord]:
            del self.board[move.target_coord]

        self.hand[self.current_player][move.piece_type] += 1

        if move.piece_type is PieceType.QUEEN:
            self.queen_coord[self.current_player] = None

    def apply_movement(self, move: Move) -> None:
        """Apply a movement move to the game state.

        Moves the top piece from the source coordinate to the target coordinate. If the
        source coordinate becomes empty, it is removed from the board. If the moved piece
        is a queen, the queen coordinate for the current player is updated.

        Args:
            move: The movement move to apply. The `source_coord` must not be `None`.

        Raises:
            ValueError: If `move.source_coord` is `None`.
        """
        if move.source_coord is None:
            msg = "Source coordinate for a movement move cannot be None."
            raise ValueError(msg)

        piece = self.board[move.source_coord].pop()

        if not self.board[move.source_coord]:
            del self.board[move.source_coord]

        self.board.setdefault(move.target_coord, []).append(piece)

        if move.piece_type is PieceType.QUEEN:
            self.queen_coord[self.current_player] = move.target_coord

    def undo_movement(self, move: Move) -> None:
        """Undo a previously applied movement move.

        Moves the top piece from the target coordinate back to the source coordinate. If
        the target coordinate becomes empty, it is removed from the board. If the moved
        piece is a queen, the queen coordinate for the current player is restored.

        Args:
            move: The movement move to undo. The `source_coord` must not be `None`.

        Raises:
            ValueError: If `move.source_coord` is `None`.
        """
        if move.source_coord is None:
            msg = "Source coordinate for a movement move cannot be None."
            raise ValueError(msg)

        piece = self.board[move.target_coord].pop()

        if not self.board[move.target_coord]:
            del self.board[move.target_coord]

        self.board.setdefault(move.source_coord, []).append(piece)

        if move.piece_type is PieceType.QUEEN:
            self.queen_coord[self.current_player] = move.source_coord

    def apply_move(self, move: Move | None) -> None:
        """Apply a move to the game state and advance the turn.

        Delegates to `apply_placement` or `apply_movement` depending on whether
        `move.source_coord` is `None`. A `None` move represents a pass. After applying the
        move, the ply counter is incremented and the current player switches to the
        opponent.

        Args:
            move: The move to apply, or `None` to pass the turn.
        """
        if move is not None:
            if move.source_coord is None:
                self.apply_placement(move)
            else:
                self.apply_movement(move)

        self.current_ply += 1
        self.current_player = self.current_player.opponent

    def undo_move(self, move: Move | None) -> None:
        """Undo the most recently applied move and revert the turn.

        Delegates to `undo_placement` or `undo_movement` depending on whether
        `move.source_coord` is `None`. A `None` move represents an undone pass. After
        undoing the move, the ply counter is decremented and the current player switches
        back.

        Args:
            move: The move to undo, or `None` if the previous turn was a pass.
        """
        self.current_ply -= 1
        self.current_player = self.current_player.opponent

        if move is not None:
            if move.source_coord is None:
                self.undo_placement(move)
            else:
                self.undo_movement(move)
