"""Game records: the rules, the starting position and the moves of a game.

A record is enough to replay a game, and like every engine value it converts to and from
JSON through `JsonCodec`:

- Board setup: `{"board": [{"coord": [q, r], "stack": [piece, ...]}, ...],
  "current_player": "white", "current_ply": 3 | null}`, with the stacks ordered by
  coordinate.
- Game record: `{"rules": ..., "setup": setup | null, "moves": [move | null, ...]}`, where
  a `null` setup is the initial state and a `null` move is a pass.

Reading JSON only checks its shape. Whether a board or move list is valid under the rules
is checked when a record is replayed.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Annotated, ClassVar

from pydantic import ConfigDict, PlainSerializer, PlainValidator, StrictInt

from hive.engine.codec import JsonCodec, json_adapter
from hive.engine.grid import Coordinate
from hive.engine.rules import Rules
from hive.engine.state import JSON_CONFIG, GameBoard, GameState, Move, Piece, Player


@dataclass(frozen=True, slots=True)
class BoardStack:
    """The JSON form of one occupied coordinate of a board.

    Attributes:
        coord: The coordinate.
        stack: The pieces on the coordinate, ordered bottom to top.
    """

    __pydantic_config__: ClassVar[ConfigDict] = JSON_CONFIG

    coord: Coordinate
    stack: list[Piece]

    @classmethod
    def from_board(cls, board: GameBoard) -> list["BoardStack"]:
        """Split a board into its stacks.

        Args:
            board: The board.

        Returns:
            One stack per occupied coordinate, ordered by coordinate.
        """
        return [cls(coord=coord, stack=board[coord]) for coord in sorted(board)]

    @classmethod
    def to_board(cls, data: object) -> GameBoard:
        """Read a board from the JSON form of its stacks.

        Args:
            data: A list of `{"coord": [q, r], "stack": [...]}` objects.

        Returns:
            The board.

        Raises:
            ValueError: If `data` is not a list of stacks, or a coordinate appears more
                than once.
        """
        stacks: list[BoardStack] = json_adapter(list[BoardStack]).validate_python(data)
        board = {stack.coord: stack.stack for stack in stacks}

        if len(board) != len(stacks):
            msg = "The board has more than one stack at the same coordinate."
            raise ValueError(msg)

        return board


type JsonBoard = Annotated[
    GameBoard,
    PlainValidator(BoardStack.to_board, json_schema_input_type=list[BoardStack]),
    PlainSerializer(BoardStack.from_board, return_type=list[BoardStack]),
]
"""A board whose JSON form is a list of stacks, since JSON keys cannot be coordinates."""


@dataclass(slots=True)
class BoardSetup(JsonCodec):
    """A starting position made in the board editor.

    Attributes:
        board: The pieces on each occupied coordinate, ordered bottom to top.
        current_player: The player to move.
        current_ply: The number of plies played so far, or `None` to derive the lowest
            consistent ply (see `Rules.from_board`).
    """

    __pydantic_config__: ClassVar[ConfigDict] = JSON_CONFIG

    board: JsonBoard
    current_player: Player
    current_ply: StrictInt | None = None

    def state(self, rules: Rules) -> GameState:
        """Create the validated game state of the setup.

        Args:
            rules: The rules the board is validated against.

        Returns:
            The game state of the setup.

        Raises:
            InvalidBoardError: If the board is not valid under `rules`.
        """
        return rules.from_board(
            board=self.board,
            current_player=self.current_player,
            current_ply=self.current_ply,
        )


@dataclass(slots=True)
class GameRecord(JsonCodec):
    """A game as its rules, starting position and moves, which is enough to replay it.

    Attributes:
        rules: The rules the game is played with.
        setup: The starting position from the board editor, or `None` for the initial
            state.
        moves: The moves played from the starting position, where `None` is a pass.
    """

    __pydantic_config__: ClassVar[ConfigDict] = JSON_CONFIG

    rules: Rules
    setup: BoardSetup | None = None
    moves: list[Move | None] = field(default_factory=list)

    def initial_state(self) -> GameState:
        """Create the validated starting state of the game.

        Returns:
            The state before the first move.

        Raises:
            InvalidBoardError: If the setup board is not valid under the rules.
        """
        if self.setup is None:
            return self.rules.create_initial_state()

        return self.setup.state(self.rules)

    def replay(self) -> GameState:
        """Replay every move, checking that each one is legal.

        Returns:
            The state after the last move.

        Raises:
            InvalidBoardError: If the setup board is not valid under the rules.
            IllegalMoveError: If a move is not legal in the state it is played in.
        """
        state = self.initial_state()

        for move in self.moves:
            self.rules.apply_checked_move(state=state, move=move)

        return state

    def states(self) -> Iterator[GameState]:
        """Iterate the states of the game, one per ply, checking every move.

        Each state is an independent copy, so callers may keep or modify it.

        Yields:
            The starting state, then the state after each move.

        Raises:
            InvalidBoardError: If the setup board is not valid under the rules.
            IllegalMoveError: If a move is not legal in the state it is played in.
        """
        state = self.initial_state()
        yield state.copy()

        for move in self.moves:
            self.rules.apply_checked_move(state=state, move=move)
            yield state.copy()
