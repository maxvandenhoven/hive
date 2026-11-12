"""The values of a game state: players, pieces, moves, boards and the state itself.

`GameState` and `Move` are classes of the Rust core (`hive._core`), re-exported here with
their documentation in `hive/_core.pyi`. `Player`, `PieceType` and `Piece` stay Python
values, which the core returns as the same objects, so identity checks such as
`piece.type is PieceType.ANT` hold.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated

from pydantic import Field, PlainSerializer, PlainValidator

from hive._core import GameState, Move
from hive.engine.codec import JsonCodec, NamedIntEnum, json_adapter
from hive.engine.grid import Coordinate

__all__ = [
    "SHARED_PIECES",
    "BoardCell",
    "GameBoard",
    "GameState",
    "Move",
    "Piece",
    "PieceType",
    "Player",
]


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
    def split_board(
        cls, board: Mapping[Coordinate, Sequence[Piece]]
    ) -> list["BoardCell"]:
        """Split a board into its occupied cells.

        Args:
            board: The board.

        Returns:
            One cell per occupied coordinate, ordered by coordinate.
        """
        return [cls(coord=coord, stack=list(board[coord])) for coord in sorted(board)]

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
