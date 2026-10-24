"""Serialization of engine values to and from JSON-compatible values.

Used by match records, gauntlet reports, the API and the database. Every value has a
`serialize_*` function, which is total, and a `deserialize_*` function, which validates
its input and raises `ValueError` with a message naming the offending value. Enums are
written as lower case names and coordinates as `[q, r]` lists:

- Move: `{"piece": "ant", "from": [q, r] | null, "to": [q, r]}`, a pass is `null`.
- Rules: an object with every `Rules` field; missing fields take their default.
- Board: a list of `{"coord": [q, r], "stack": [{"piece": ..., "owner": ...}]}`.
- Setup: `"initial"`, or `{"board": ..., "current_player": ..., "current_ply": ...}`.
- Game record: `{"rules": ..., "setup": ..., "moves": [...]}`.

Deserializers only check the shape of their input. Whether a board or move list is valid
under the rules is checked when a `GameRecord` is replayed.
"""

from collections.abc import Iterator, Set
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TypeIs

from hive.engine.grid import Coordinate
from hive.engine.rules import Rules
from hive.engine.state import GameBoard, GameState, Move, Piece, PieceType, Player

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
"""A value that `json.dumps` can write and `json.loads` can return."""

INITIAL_SETUP = "initial"
"""The serialized setup of a game that starts from the initial state."""


@dataclass(slots=True)
class BoardSetup:
    """A starting position made in the board editor.

    Attributes:
        board: The pieces on each occupied coordinate, ordered bottom to top.
        current_player: The player to move.
        current_ply: The number of plies played so far, or `None` to derive the lowest
            consistent ply (see `Rules.from_board`).
    """

    board: GameBoard
    current_player: Player
    current_ply: int | None = None

    def state(self, rules: Rules) -> GameState:
        """Create the validated game state of the setup.

        Args:
            rules: The rules the board is validated against.

        Returns:
            The game state of the setup.

        Raises:
            InvalidBoardError: If the board is not valid under `rules`.
        """
        return rules.from_board(self.board, self.current_player, self.current_ply)


@dataclass(slots=True)
class GameRecord:
    """A game as its rules, starting position and moves, which is enough to replay it.

    Attributes:
        rules: The rules the game is played with.
        setup: The starting position from the board editor, or `None` for the initial
            state.
        moves: The moves played from the starting position, where `None` is a pass.
    """

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
            self.rules.apply_checked_move(state, move)
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
            self.rules.apply_checked_move(state, move)
            yield state.copy()


def serialize_player(player: Player) -> str:
    """Serialize a player as its lower case name, for example `white`.

    Args:
        player: The player to serialize.

    Returns:
        The lower case name of the player.
    """
    return player.name.lower()


def deserialize_player(data: object) -> Player:
    """Deserialize a player from its lower case name.

    Args:
        data: The serialized player.

    Returns:
        The player.

    Raises:
        ValueError: If `data` is not the name of a player.
    """
    return _deserialize_enum(data, Player, "player")


def serialize_piece_type(piece_type: PieceType) -> str:
    """Serialize a piece type as its lower case name, for example `ant`.

    Args:
        piece_type: The piece type to serialize.

    Returns:
        The lower case name of the piece type.
    """
    return piece_type.name.lower()


def deserialize_piece_type(data: object) -> PieceType:
    """Deserialize a piece type from its lower case name.

    Args:
        data: The serialized piece type.

    Returns:
        The piece type.

    Raises:
        ValueError: If `data` is not the name of a piece type.
    """
    return _deserialize_enum(data, PieceType, "piece type")


def serialize_coordinate(coord: Coordinate) -> list[JsonValue]:
    """Serialize a coordinate as a `[q, r]` list.

    Args:
        coord: The axial coordinate to serialize.

    Returns:
        The coordinate as a list of two integers.
    """
    return [coord[0], coord[1]]


def deserialize_coordinate(data: object) -> Coordinate:
    """Deserialize a coordinate from a `[q, r]` list.

    Args:
        data: The serialized coordinate.

    Returns:
        The axial coordinate.

    Raises:
        ValueError: If `data` is not a list of two integers.
    """
    if (
        not isinstance(data, list | tuple)
        or len(data) != 2
        or not all(_is_int(value) for value in data)
    ):
        msg = f"Expected a coordinate as a list of two integers, but got `{data!r}`."
        raise ValueError(msg)

    return (data[0], data[1])


def serialize_move(move: Move | None) -> JsonValue:
    """Serialize a move, or a pass as `None`.

    Args:
        move: The move to serialize, or `None` for a pass.

    Returns:
        An object with the `piece`, the `from` coordinate (`None` for a placement) and the
        `to` coordinate, or `None` for a pass.
    """
    if move is None:
        return None

    return {
        "piece": serialize_piece_type(move.piece_type),
        "from": (
            None if move.source_coord is None else serialize_coordinate(move.source_coord)
        ),
        "to": serialize_coordinate(move.target_coord),
    }


def deserialize_move(data: object) -> Move | None:
    """Deserialize a move, where `None` is a pass.

    Args:
        data: The serialized move.

    Returns:
        The move, or `None` for a pass.

    Raises:
        ValueError: If `data` is not `None` or a valid move object.
    """
    if data is None:
        return None

    fields = _expect_object(data, "move", required={"piece", "from", "to"})
    source = fields["from"]
    return Move(
        piece_type=deserialize_piece_type(fields["piece"]),
        source_coord=None if source is None else deserialize_coordinate(source),
        target_coord=deserialize_coordinate(fields["to"]),
    )


def serialize_rules(rules: Rules) -> dict[str, JsonValue]:
    """Serialize rules as an object with every field.

    Args:
        rules: The rules to serialize.

    Returns:
        The rules, with `piece_counts` keyed by piece type name.
    """
    return {
        "piece_counts": {
            serialize_piece_type(piece_type): count
            for piece_type, count in rules.piece_counts.items()
        },
        "starting_player": serialize_player(rules.starting_player),
        "queen_by_turn": rules.queen_by_turn,
        "allow_queen_first_turn": rules.allow_queen_first_turn,
        "move_before_queen": rules.move_before_queen,
        "max_turns": rules.max_turns,
    }


def deserialize_rules(data: object) -> Rules:
    """Deserialize rules from an object of fields, where missing fields use their default.

    Args:
        data: The serialized rules.

    Returns:
        The rules.

    Raises:
        ValueError: If `data` is not an object, has unknown fields or fields of the wrong
            type, or describes an invalid configuration.
    """
    defaults = serialize_rules(Rules())
    fields = defaults | _expect_object(data, "rules", optional=defaults.keys())

    try:
        return Rules(
            piece_counts=_deserialize_piece_counts(fields["piece_counts"]),
            starting_player=deserialize_player(fields["starting_player"]),
            queen_by_turn=_expect_optional_int(fields["queen_by_turn"], "queen_by_turn"),
            allow_queen_first_turn=_expect_bool(
                fields["allow_queen_first_turn"], "allow_queen_first_turn"
            ),
            move_before_queen=_expect_bool(
                fields["move_before_queen"], "move_before_queen"
            ),
            max_turns=_expect_optional_int(fields["max_turns"], "max_turns"),
        )
    except ValueError as e:
        msg = f"Invalid rules: {e}"
        raise ValueError(msg) from e


def serialize_board(board: GameBoard) -> list[JsonValue]:
    """Serialize a board as a list of stacks, ordered by coordinate.

    Args:
        board: The board to serialize.

    Returns:
        One object per occupied coordinate with its `coord` and its `stack` of pieces,
        ordered bottom to top.
    """
    return [
        {
            "coord": serialize_coordinate(coord),
            "stack": [_serialize_piece(piece) for piece in board[coord]],
        }
        for coord in sorted(board)
    ]


def deserialize_board(data: object) -> GameBoard:
    """Deserialize a board from a list of stacks.

    Only the shape is checked; `Rules.from_board` checks that the board is valid.

    Args:
        data: The serialized board.

    Returns:
        The board.

    Raises:
        ValueError: If `data` is not a list of stack objects, or a coordinate appears
            more than once.
    """
    if not isinstance(data, list):
        msg = f"Expected a board as a list of stacks, but got `{data!r}`."
        raise ValueError(msg)

    board: GameBoard = {}
    for entry in data:
        fields = _expect_object(entry, "stack", required={"coord", "stack"})
        coord = deserialize_coordinate(fields["coord"])
        if coord in board:
            msg = f"The board has more than one stack at coordinate `{coord}`."
            raise ValueError(msg)

        pieces = fields["stack"]
        if not isinstance(pieces, list):
            msg = f"Expected the stack at `{coord}` to be a list, but got `{pieces!r}`."
            raise ValueError(msg)
        board[coord] = [_deserialize_piece(piece) for piece in pieces]

    return board


def serialize_setup(setup: BoardSetup | None) -> JsonValue:
    """Serialize a game setup, where `None` is the initial state.

    Args:
        setup: The board editor setup, or `None` for the initial state.

    Returns:
        `"initial"`, or an object with the `board`, `current_player` and `current_ply`.
    """
    if setup is None:
        return INITIAL_SETUP

    return {
        "board": serialize_board(setup.board),
        "current_player": serialize_player(setup.current_player),
        "current_ply": setup.current_ply,
    }


def deserialize_setup(data: object) -> BoardSetup | None:
    """Deserialize a game setup, where `"initial"` is the initial state.

    Args:
        data: The serialized setup.

    Returns:
        The board editor setup, or `None` for the initial state.

    Raises:
        ValueError: If `data` is not `"initial"` or a valid setup object.
    """
    if data == INITIAL_SETUP:
        return None

    fields = _expect_object(
        data, "setup", required={"board", "current_player"}, optional={"current_ply"}
    )
    return BoardSetup(
        board=deserialize_board(fields["board"]),
        current_player=deserialize_player(fields["current_player"]),
        current_ply=_expect_optional_int(fields.get("current_ply"), "current_ply"),
    )


def serialize_record(record: GameRecord) -> dict[str, JsonValue]:
    """Serialize a game record.

    Args:
        record: The game record to serialize.

    Returns:
        An object with the `rules`, the `setup` and the list of `moves`.
    """
    return {
        "rules": serialize_rules(record.rules),
        "setup": serialize_setup(record.setup),
        "moves": [serialize_move(move) for move in record.moves],
    }


def deserialize_record(data: object) -> GameRecord:
    """Deserialize a game record.

    Only the shape is checked; `GameRecord.replay` checks that the moves are legal.

    Args:
        data: The serialized game record.

    Returns:
        The game record.

    Raises:
        ValueError: If `data` is not a valid game record object.
    """
    fields = _expect_object(data, "game record", required={"rules", "setup", "moves"})
    moves = fields["moves"]
    if not isinstance(moves, list):
        msg = f"Expected `moves` to be a list, but got `{moves!r}`."
        raise ValueError(msg)

    deserialized_moves: list[Move | None] = []
    for index, move in enumerate(moves):
        try:
            deserialized_moves.append(deserialize_move(move))
        except ValueError as e:
            msg = f"Invalid move at index `{index}`: {e}"
            raise ValueError(msg) from e

    return GameRecord(
        rules=deserialize_rules(fields["rules"]),
        setup=deserialize_setup(fields["setup"]),
        moves=deserialized_moves,
    )


def _serialize_piece(piece: Piece) -> JsonValue:
    """Serialize a piece as an object with its `piece` type and `owner`."""
    return {
        "piece": serialize_piece_type(piece.type),
        "owner": serialize_player(piece.owner),
    }


def _deserialize_piece(data: object) -> Piece:
    """Deserialize a piece from an object with its `piece` type and `owner`.

    Raises:
        ValueError: If `data` is not a valid piece object.
    """
    fields = _expect_object(data, "piece", required={"piece", "owner"})
    return Piece(
        type=deserialize_piece_type(fields["piece"]),
        owner=deserialize_player(fields["owner"]),
    )


def _deserialize_piece_counts(data: object) -> dict[PieceType, int]:
    """Deserialize piece counts from an object keyed by piece type name.

    Raises:
        ValueError: If `data` is not an object, a key is not a piece type, or a count is
            not a non-negative integer.
    """
    if not isinstance(data, dict):
        msg = f"Expected `piece_counts` to be an object, but got `{data!r}`."
        raise ValueError(msg)

    piece_counts: dict[PieceType, int] = {}
    for name, count in data.items():
        if not _is_int(count) or count < 0:
            msg = (
                f"Expected the count of `{name}` to be a non-negative integer, but got "
                f"`{count!r}`."
            )
            raise ValueError(msg)
        piece_counts[deserialize_piece_type(name)] = count

    return piece_counts


def _deserialize_enum[E: IntEnum](data: object, enum: type[E], kind: str) -> E:
    """Deserialize an enum member from its lower case name.

    Raises:
        ValueError: If `data` is not the lower case name of a member.
    """
    if (
        not isinstance(data, str)
        or data != data.lower()
        or data.upper() not in enum.__members__
    ):
        msg = f"Unknown {kind} `{data}`."
        raise ValueError(msg)

    return enum[data.upper()]


def _expect_object(
    data: object,
    kind: str,
    required: Set[str] = frozenset(),
    optional: Set[str] = frozenset(),
) -> dict[str, object]:
    """Check that a value is an object with the required and no unknown keys.

    Raises:
        ValueError: If `data` is not an object, misses a required key or has an unknown
            key.
    """
    if not isinstance(data, dict):
        msg = f"Expected a {kind} object, but got `{data!r}`."
        raise ValueError(msg)

    missing = required - data.keys()
    if missing:
        msg = f"The {kind} object is missing the keys `{sorted(missing)}`."
        raise ValueError(msg)

    unknown = data.keys() - required - optional
    if unknown:
        msg = f"The {kind} object has the unknown keys `{sorted(unknown)}`."
        raise ValueError(msg)

    return data


def _expect_optional_int(value: object, name: str) -> int | None:
    """Check that a field value is an integer or `None`.

    Raises:
        ValueError: If `value` is neither an integer nor `None`.
    """
    if value is not None and not _is_int(value):
        msg = f"Expected `{name}` to be an integer or null, but got `{value!r}`."
        raise ValueError(msg)

    return value


def _expect_bool(value: object, name: str) -> bool:
    """Check that a field value is a boolean.

    Raises:
        ValueError: If `value` is not a boolean.
    """
    if not isinstance(value, bool):
        msg = f"Expected `{name}` to be a boolean, but got `{value!r}`."
        raise ValueError(msg)

    return value


def _is_int(value: object) -> TypeIs[int]:
    """Check that a value is an integer, excluding booleans."""
    return isinstance(value, int) and not isinstance(value, bool)
