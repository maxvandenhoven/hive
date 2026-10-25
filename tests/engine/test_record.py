import json
import random

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue, ValidationError

from hive.engine.codec import json_adapter
from hive.engine.errors import IllegalMoveError, InvalidBoardError
from hive.engine.grid import Coordinate
from hive.engine.record import BoardSetup, GameRecord, JsonBoard
from hive.engine.rules import Rules
from hive.engine.state import GameBoard, GameState, Move, Piece, PieceType, Player

coord_strategy = st.tuples(st.integers(-50, 50), st.integers(-50, 50))
move_strategy = st.none() | st.builds(
    Move,
    piece_type=st.sampled_from(PieceType),
    source_coord=st.none() | coord_strategy,
    target_coord=coord_strategy,
)
piece_strategy = st.builds(
    Piece, type=st.sampled_from(PieceType), owner=st.sampled_from(Player)
)
board_strategy = st.dictionaries(
    coord_strategy, st.lists(piece_strategy, min_size=1, max_size=4), max_size=8
)
setup_strategy = st.none() | st.builds(
    BoardSetup,
    board=board_strategy,
    current_player=st.sampled_from(Player),
    current_ply=st.none() | st.integers(0, 200),
)


@st.composite
def rules_strategy(draw: st.DrawFn) -> Rules:
    """Draw a valid rules configuration."""
    other_types = [
        piece_type for piece_type in PieceType if piece_type is not PieceType.QUEEN
    ]
    piece_counts = {PieceType.QUEEN: 1} | draw(
        st.dictionaries(st.sampled_from(other_types), st.integers(0, 4))
    )
    queen_by_turn = draw(st.none() | st.integers(1, 10))
    allow_queen_first_turn = draw(st.booleans()) or queen_by_turn == 1

    return Rules(
        piece_counts=piece_counts,
        starting_player=draw(st.sampled_from(Player)),
        queen_by_turn=queen_by_turn,
        allow_queen_first_turn=allow_queen_first_turn,
        move_before_queen=draw(st.booleans()),
        max_turns=draw(st.none() | st.integers(1, 100)),
    )


record_strategy = st.builds(
    GameRecord,
    rules=rules_strategy(),
    setup=setup_strategy,
    moves=st.lists(move_strategy, max_size=10),
)


def round_trip(kind: object, value: object) -> object:
    """Write a value of a type as JSON text and read it back."""
    adapter = json_adapter(kind)

    return adapter.validate_json(adapter.dump_json(value, by_alias=True))


def to_json(kind: object, value: object) -> JsonValue:
    """Serialize a value of a type."""
    return json_adapter(kind).dump_python(value, mode="json", by_alias=True)


def error_locations(kind: object, data: object) -> list[str]:
    """Validate invalid data and return the dotted location of every error."""
    with pytest.raises(ValidationError) as info:
        json_adapter(kind).validate_python(data)

    return [".".join(str(part) for part in error["loc"]) for error in info.value.errors()]


def snapshot(state: GameState) -> tuple[object, ...]:
    """Capture every field of a state for comparison."""
    return (
        {coord: list(stack) for coord, stack in state.board.items()},
        state.current_player,
        state.current_ply,
        {player: dict(hand) for player, hand in state.hand.items()},
        dict(state.queen_coord),
    )


def random_game(rules: Rules, plies: int, seed: int) -> list[Move | None]:
    """Play a seeded random game and return its moves."""
    rng = random.Random(seed)
    state = rules.create_initial_state()
    moves: list[Move | None] = []

    while len(moves) < plies and not rules.is_finished(state):
        move = rng.choice(rules.legal_moves(state))
        state.apply_move(move)
        moves.append(move)

    return moves


class TestRoundTrip:
    @given(st.sampled_from(Player))
    def test_player(self, player: Player) -> None:
        assert round_trip(kind=Player, value=player) is player

    @given(st.sampled_from(PieceType))
    def test_piece_type(self, piece_type: PieceType) -> None:
        assert round_trip(kind=PieceType, value=piece_type) is piece_type

    @given(coord_strategy)
    def test_coordinate(self, coord: Coordinate) -> None:
        assert round_trip(kind=Coordinate, value=coord) == coord

    @given(move_strategy)
    def test_move(self, move: Move | None) -> None:
        assert round_trip(kind=Move | None, value=move) == move

    @given(rules_strategy())
    def test_rules(self, rules: Rules) -> None:
        assert round_trip(kind=Rules, value=rules) == rules

    @given(board_strategy)
    def test_board(self, board: GameBoard) -> None:
        assert round_trip(kind=JsonBoard, value=board) == board

    @given(setup_strategy)
    def test_setup(self, setup: BoardSetup | None) -> None:
        assert round_trip(kind=BoardSetup | None, value=setup) == setup

    @given(record_strategy)
    def test_record(self, record: GameRecord) -> None:
        assert GameRecord.from_json(json.loads(json.dumps(record.to_json()))) == record


class TestFormat:
    def test_move(self) -> None:
        move = Move(piece_type=PieceType.ANT, source_coord=(0, -1), target_coord=(1, 0))

        assert move.to_json() == {"piece": "ant", "from": [0, -1], "to": [1, 0]}
        assert to_json(kind=Move | None, value=None) is None

    def test_placement(self) -> None:
        move = Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0))

        assert move.to_json() == {"piece": "queen", "from": None, "to": [0, 0]}

    def test_rules(self) -> None:
        assert Rules().to_json() == {
            "piece_counts": {
                "queen": 1,
                "beetle": 2,
                "grasshopper": 3,
                "spider": 2,
                "ant": 3,
            },
            "starting_player": "white",
            "queen_by_turn": 4,
            "allow_queen_first_turn": True,
            "move_before_queen": False,
            "max_turns": None,
        }

    def test_board_is_ordered_by_coordinate(self) -> None:
        board: GameBoard = {
            (1, 0): [Piece(type=PieceType.ANT, owner=Player.BLACK)],
            (0, 0): [
                Piece(type=PieceType.QUEEN, owner=Player.WHITE),
                Piece(type=PieceType.BEETLE, owner=Player.BLACK),
            ],
        }

        assert to_json(kind=JsonBoard, value=board) == [
            {
                "coord": [0, 0],
                "stack": [
                    {"piece": "queen", "owner": "white"},
                    {"piece": "beetle", "owner": "black"},
                ],
            },
            {"coord": [1, 0], "stack": [{"piece": "ant", "owner": "black"}]},
        ]

    def test_initial_setup(self) -> None:
        assert GameRecord(rules=Rules()).to_json() == {
            "rules": Rules().to_json(),
            "setup": None,
            "moves": [],
        }

    def test_rules_missing_fields_use_defaults(self) -> None:
        assert Rules.from_json({}) == Rules()
        assert Rules.from_json({"starting_player": "black"}) == Rules(
            starting_player=Player.BLACK
        )

    def test_setup_without_ply(self) -> None:
        setup = BoardSetup.from_json({"board": [], "current_player": "white"})

        assert setup == BoardSetup(board={}, current_player=Player.WHITE)


class TestMalformed:
    @pytest.mark.parametrize("data", ["White", "red", 0, "ANT", None])
    def test_player(self, data: object) -> None:
        assert error_locations(kind=Player, data=data)

    @pytest.mark.parametrize("data", ["ladybug", "ANT", None, 4])
    def test_piece_type(self, data: object) -> None:
        assert error_locations(kind=PieceType, data=data)

    @pytest.mark.parametrize(
        "data", [[0], [0, 0, 0], [0, "1"], [0, 1.5], [True, 0], "0,0"]
    )
    def test_coordinate(self, data: object) -> None:
        assert error_locations(kind=Coordinate, data=data)

    @pytest.mark.parametrize(
        ("data", "location"),
        [
            ("pass", ""),
            ({"piece": "ant", "to": [0, 0]}, "from"),
            ({"piece": "ant", "from": None, "to": [0, 0], "by": "white"}, "by"),
            ({"piece": "ladybug", "from": None, "to": [0, 0]}, "piece"),
            ({"piece": "ant", "from": None, "to": None}, "to"),
        ],
    )
    def test_move(self, data: object, location: str) -> None:
        assert location in error_locations(kind=Move, data=data)[0]

    @pytest.mark.parametrize(
        ("data", "location"),
        [
            ({"max_turn": 10}, "max_turn"),
            ({"queen_by_turn": "4"}, "queen_by_turn"),
            ({"max_turns": True}, "max_turns"),
            ({"move_before_queen": 1}, "move_before_queen"),
            ({"starting_player": "red"}, "starting_player"),
            ({"piece_counts": [1]}, "piece_counts"),
            ({"piece_counts": {"queen": 1, "ant": -1}}, "piece_counts.ant"),
            ({"piece_counts": {"queen": 1, "mosquito": 1}}, "piece_counts.mosquito"),
        ],
    )
    def test_rules_shape(self, data: object, location: str) -> None:
        assert location in error_locations(kind=Rules, data=data)[0]

    @pytest.mark.parametrize(
        ("data", "match"),
        [
            ({"piece_counts": {"ant": 3}}, "exactly one queen"),
            (
                {"queen_by_turn": 1, "allow_queen_first_turn": False},
                "cannot be required on the first turn",
            ),
        ],
    )
    def test_rules_configuration(self, data: object, match: str) -> None:
        with pytest.raises(ValidationError, match=match):
            Rules.from_json(data)

    @pytest.mark.parametrize(
        ("data", "location"),
        [
            ({}, "board"),
            ([[0, 0]], "board.0"),
            ([{"coord": [0, 0], "stack": "ant"}], "board.0.stack"),
            ([{"coord": [0, 0], "stack": [{"piece": "ant"}]}], "board.0.stack.0.owner"),
            ([{"coord": [0, 0], "stack": []}, {"coord": [0, 0], "stack": []}], "board"),
        ],
    )
    def test_board(self, data: object, location: str) -> None:
        setup = {"board": data, "current_player": "white"}

        assert error_locations(kind=BoardSetup, data=setup) == [location]

    @pytest.mark.parametrize(
        ("data", "location"),
        [
            ("start", ""),
            ({"board": []}, "current_player"),
            ({"board": [], "current_player": "white", "current_ply": "3"}, "current_ply"),
        ],
    )
    def test_setup(self, data: object, location: str) -> None:
        assert location in error_locations(kind=BoardSetup, data=data)[0]

    @pytest.mark.parametrize(
        ("data", "location"),
        [
            (None, ""),
            ({"setup": None, "moves": []}, "rules"),
            ({"rules": {}, "setup": "initial", "moves": []}, "setup"),
            ({"rules": {}, "moves": {}}, "moves"),
            ({"rules": {}, "moves": [None, {"piece": "ant"}]}, "moves.1"),
        ],
    )
    def test_record(self, data: object, location: str) -> None:
        assert location in error_locations(kind=GameRecord, data=data)[0]


class TestGameRecord:
    @pytest.mark.parametrize("seed", range(5))
    def test_replay_matches_fast_path(self, seed: int) -> None:
        rules = Rules()
        moves = random_game(rules=rules, plies=60, seed=seed)
        state = rules.create_initial_state()

        for move in moves:
            state.apply_move(move)

        record = GameRecord.from_json(
            json.loads(json.dumps(GameRecord(rules=rules, moves=moves).to_json()))
        )

        assert snapshot(record.replay()) == snapshot(state)

    def test_states(self) -> None:
        rules = Rules()
        moves = random_game(rules=rules, plies=20, seed=0)
        record = GameRecord(rules=rules, moves=moves)

        states = list(record.states())

        assert len(states) == len(moves) + 1
        assert [state.current_ply for state in states] == list(range(len(moves) + 1))
        assert snapshot(states[-1]) == snapshot(record.replay())

    def test_states_are_independent(self) -> None:
        rules = Rules()
        record = GameRecord(rules=rules, moves=random_game(rules=rules, plies=4, seed=0))

        states = list(record.states())
        states[0].apply_move(rules.legal_moves(states[0])[0])

        assert states[0].current_ply == 1
        assert states[1].current_ply == 1
        assert states[1].board

    def test_rejects_illegal_move(self) -> None:
        move = Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        record = GameRecord(rules=Rules(), moves=[move, move])

        with pytest.raises(IllegalMoveError, match="ply `1`"):
            record.replay()

        with pytest.raises(IllegalMoveError):
            list(record.states())

    def test_rejects_pass_with_legal_moves(self) -> None:
        with pytest.raises(IllegalMoveError):
            GameRecord(rules=Rules(), moves=[None]).replay()

    def test_replay_from_setup(self) -> None:
        rules = Rules()
        board: GameBoard = {
            (0, 0): [Piece(type=PieceType.QUEEN, owner=Player.WHITE)],
            (1, 0): [Piece(type=PieceType.QUEEN, owner=Player.BLACK)],
        }
        setup = BoardSetup(board=board, current_player=Player.WHITE)
        move = Move(piece_type=PieceType.QUEEN, source_coord=(0, 0), target_coord=(1, -1))

        state = GameRecord(rules=rules, setup=setup, moves=[move]).replay()

        assert state.current_ply == 3
        assert state.queen_coord[Player.WHITE] == (1, -1)

    def test_rejects_invalid_setup(self) -> None:
        board: GameBoard = {
            (0, 0): [Piece(type=PieceType.ANT, owner=Player.WHITE)],
            (2, 0): [Piece(type=PieceType.ANT, owner=Player.BLACK)],
        }
        setup = BoardSetup(board=board, current_player=Player.WHITE)

        with pytest.raises(InvalidBoardError, match="connected"):
            GameRecord(rules=Rules(), setup=setup).replay()

    def test_setup_board_is_copied(self) -> None:
        board: GameBoard = {(0, 0): [Piece(type=PieceType.ANT, owner=Player.WHITE)]}
        record = GameRecord(
            rules=Rules(), setup=BoardSetup(board=board, current_player=Player.BLACK)
        )

        record.replay().board[(0, 0)].append(
            Piece(type=PieceType.BEETLE, owner=Player.BLACK)
        )

        assert board == {(0, 0): [Piece(type=PieceType.ANT, owner=Player.WHITE)]}
