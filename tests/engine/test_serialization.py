import json
import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hive.engine.errors import IllegalMoveError, InvalidBoardError
from hive.engine.grid import Coordinate
from hive.engine.rules import Rules
from hive.engine.serialization import (
    BoardSetup,
    GameRecord,
    JsonValue,
    deserialize_board,
    deserialize_coordinate,
    deserialize_move,
    deserialize_piece_type,
    deserialize_player,
    deserialize_record,
    deserialize_rules,
    deserialize_setup,
    serialize_board,
    serialize_coordinate,
    serialize_move,
    serialize_piece_type,
    serialize_player,
    serialize_record,
    serialize_rules,
    serialize_setup,
)
from hive.engine.state import GameBoard, GameState, Move, Piece, PieceType, Player

_coords = st.tuples(st.integers(-50, 50), st.integers(-50, 50))
_moves = st.none() | st.builds(
    Move,
    piece_type=st.sampled_from(PieceType),
    source_coord=st.none() | _coords,
    target_coord=_coords,
)
_pieces = st.builds(Piece, type=st.sampled_from(PieceType), owner=st.sampled_from(Player))
_boards = st.dictionaries(_coords, st.lists(_pieces, min_size=1, max_size=4), max_size=8)
_setups = st.none() | st.builds(
    BoardSetup,
    board=_boards,
    current_player=st.sampled_from(Player),
    current_ply=st.none() | st.integers(0, 200),
)


@st.composite
def _rules(draw: st.DrawFn) -> Rules:
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


_records = st.builds(
    GameRecord, rules=_rules(), setup=_setups, moves=st.lists(_moves, max_size=10)
)


def _through_json(data: JsonValue) -> object:
    """Write and read a serialized value as JSON, which turns tuples into lists."""
    return json.loads(json.dumps(data))


def _snapshot(state: GameState) -> tuple[object, ...]:
    """Capture every field of a state for comparison."""
    return (
        {coord: list(stack) for coord, stack in state.board.items()},
        state.current_player,
        state.current_ply,
        {player: dict(hand) for player, hand in state.hand.items()},
        dict(state.queen_coord),
    )


def _random_game(rules: Rules, plies: int, seed: int) -> list[Move | None]:
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
        assert deserialize_player(_through_json(serialize_player(player))) is player

    @given(st.sampled_from(PieceType))
    def test_piece_type(self, piece_type: PieceType) -> None:
        data = _through_json(serialize_piece_type(piece_type))

        assert deserialize_piece_type(data) is piece_type

    @given(_coords)
    def test_coordinate(self, coord: Coordinate) -> None:
        assert deserialize_coordinate(_through_json(serialize_coordinate(coord))) == coord

    @given(_moves)
    def test_move(self, move: Move | None) -> None:
        assert deserialize_move(_through_json(serialize_move(move))) == move

    @given(_rules())
    def test_rules(self, rules: Rules) -> None:
        assert deserialize_rules(_through_json(serialize_rules(rules))) == rules

    @given(_boards)
    def test_board(self, board: GameBoard) -> None:
        assert deserialize_board(_through_json(serialize_board(board))) == board

    @given(_setups)
    def test_setup(self, setup: BoardSetup | None) -> None:
        assert deserialize_setup(_through_json(serialize_setup(setup))) == setup

    @given(_records)
    def test_record(self, record: GameRecord) -> None:
        assert deserialize_record(_through_json(serialize_record(record))) == record


class TestFormat:
    def test_move(self) -> None:
        move = Move(piece_type=PieceType.ANT, source_coord=(0, -1), target_coord=(1, 0))

        assert serialize_move(move) == {"piece": "ant", "from": [0, -1], "to": [1, 0]}
        assert serialize_move(None) is None

    def test_placement(self) -> None:
        move = Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0))

        assert serialize_move(move) == {"piece": "queen", "from": None, "to": [0, 0]}

    def test_rules(self) -> None:
        assert serialize_rules(Rules()) == {
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
            (1, 0): [Piece(PieceType.ANT, Player.BLACK)],
            (0, 0): [
                Piece(PieceType.QUEEN, Player.WHITE),
                Piece(PieceType.BEETLE, Player.BLACK),
            ],
        }

        assert serialize_board(board) == [
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
        assert serialize_setup(None) == "initial"

    def test_rules_missing_fields_use_defaults(self) -> None:
        assert deserialize_rules({}) == Rules()
        assert deserialize_rules({"starting_player": "black"}) == Rules(
            starting_player=Player.BLACK
        )

    def test_setup_without_ply(self) -> None:
        setup = deserialize_setup({"board": [], "current_player": "white"})

        assert setup == BoardSetup(board={}, current_player=Player.WHITE)


class TestMalformed:
    @pytest.mark.parametrize(
        ("data", "match"),
        [
            ("White", "Unknown player `White`"),
            ("red", "Unknown player `red`"),
            (0, "Unknown player `0`"),
        ],
    )
    def test_player(self, data: object, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            deserialize_player(data)

    @pytest.mark.parametrize("data", ["ladybug", "ANT", None])
    def test_piece_type(self, data: object) -> None:
        with pytest.raises(ValueError, match="Unknown piece type"):
            deserialize_piece_type(data)

    @pytest.mark.parametrize(
        "data", [[0], [0, 0, 0], [0, "1"], [0, 1.5], [True, 0], "0,0"]
    )
    def test_coordinate(self, data: object) -> None:
        with pytest.raises(ValueError, match="list of two integers"):
            deserialize_coordinate(data)

    @pytest.mark.parametrize(
        ("data", "match"),
        [
            ("pass", "Expected a move object"),
            ({"piece": "ant", "to": [0, 0]}, r"missing the keys `\['from'\]`"),
            (
                {"piece": "ant", "from": None, "to": [0, 0], "by": "white"},
                r"unknown keys `\['by'\]`",
            ),
            ({"piece": "ladybug", "from": None, "to": [0, 0]}, "Unknown piece type"),
            ({"piece": "ant", "from": None, "to": None}, "list of two integers"),
        ],
    )
    def test_move(self, data: object, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            deserialize_move(data)

    @pytest.mark.parametrize(
        ("data", "match"),
        [
            ([], "Expected a rules object"),
            ({"max_turn": 10}, r"unknown keys `\['max_turn'\]`"),
            ({"queen_by_turn": "4"}, "`queen_by_turn` to be an integer or null"),
            ({"max_turns": True}, "`max_turns` to be an integer or null"),
            ({"move_before_queen": 1}, "`move_before_queen` to be a boolean"),
            ({"starting_player": "red"}, "Unknown player `red`"),
            ({"piece_counts": [1]}, "`piece_counts` to be an object"),
            ({"piece_counts": {"queen": 1, "ant": -1}}, "count of `ant`"),
            ({"piece_counts": {"queen": 1, "mosquito": 1}}, "Unknown piece type"),
            ({"piece_counts": {"ant": 3}}, "exactly one queen"),
            (
                {"queen_by_turn": 1, "allow_queen_first_turn": False},
                "cannot be required on the first turn",
            ),
        ],
    )
    def test_rules(self, data: object, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            deserialize_rules(data)

    @pytest.mark.parametrize(
        ("data", "match"),
        [
            ({}, "Expected a board as a list"),
            ([[0, 0]], "Expected a stack object"),
            ([{"coord": [0, 0], "stack": "ant"}], "stack at `\\(0, 0\\)` to be a list"),
            (
                [{"coord": [0, 0], "stack": [{"piece": "ant"}]}],
                r"piece object is missing the keys `\['owner'\]`",
            ),
            (
                [{"coord": [0, 0], "stack": []}, {"coord": [0, 0], "stack": []}],
                "more than one stack at coordinate",
            ),
        ],
    )
    def test_board(self, data: object, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            deserialize_board(data)

    @pytest.mark.parametrize(
        ("data", "match"),
        [
            ("start", "Expected a setup object"),
            ({"board": []}, r"missing the keys `\['current_player'\]`"),
            (
                {"board": [], "current_player": "white", "current_ply": "3"},
                "`current_ply` to be an integer or null",
            ),
        ],
    )
    def test_setup(self, data: object, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            deserialize_setup(data)

    @pytest.mark.parametrize(
        ("data", "match"),
        [
            (None, "Expected a game record object"),
            ({"rules": {}, "moves": []}, r"missing the keys `\['setup'\]`"),
            ({"rules": {}, "setup": "initial", "moves": {}}, "`moves` to be a list"),
            (
                {"rules": {}, "setup": "initial", "moves": [None, {"piece": "ant"}]},
                "Invalid move at index `1`",
            ),
        ],
    )
    def test_record(self, data: object, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            deserialize_record(data)


class TestGameRecord:
    @pytest.mark.parametrize("seed", range(5))
    def test_replay_matches_fast_path(self, seed: int) -> None:
        rules = Rules()
        moves = _random_game(rules, plies=60, seed=seed)
        state = rules.create_initial_state()
        for move in moves:
            state.apply_move(move)

        record = deserialize_record(
            _through_json(serialize_record(GameRecord(rules=rules, moves=moves)))
        )

        assert _snapshot(record.replay()) == _snapshot(state)

    def test_states(self) -> None:
        rules = Rules()
        moves = _random_game(rules, plies=20, seed=0)
        record = GameRecord(rules=rules, moves=moves)

        states = list(record.states())

        assert len(states) == len(moves) + 1
        assert [state.current_ply for state in states] == list(range(len(moves) + 1))
        assert _snapshot(states[-1]) == _snapshot(record.replay())

    def test_states_are_independent(self) -> None:
        rules = Rules()
        record = GameRecord(rules=rules, moves=_random_game(rules, plies=4, seed=0))

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
            (0, 0): [Piece(PieceType.QUEEN, Player.WHITE)],
            (1, 0): [Piece(PieceType.QUEEN, Player.BLACK)],
        }
        setup = BoardSetup(board=board, current_player=Player.WHITE)
        move = Move(piece_type=PieceType.QUEEN, source_coord=(0, 0), target_coord=(1, -1))

        state = GameRecord(rules=rules, setup=setup, moves=[move]).replay()

        assert state.current_ply == 3
        assert state.queen_coord[Player.WHITE] == (1, -1)

    def test_rejects_invalid_setup(self) -> None:
        board: GameBoard = {
            (0, 0): [Piece(PieceType.ANT, Player.WHITE)],
            (2, 0): [Piece(PieceType.ANT, Player.BLACK)],
        }
        setup = BoardSetup(board=board, current_player=Player.WHITE)

        with pytest.raises(InvalidBoardError, match="connected"):
            GameRecord(rules=Rules(), setup=setup).replay()

    def test_setup_board_is_copied(self) -> None:
        board: GameBoard = {(0, 0): [Piece(PieceType.ANT, Player.WHITE)]}
        record = GameRecord(
            rules=Rules(), setup=BoardSetup(board=board, current_player=Player.BLACK)
        )

        record.replay().board[(0, 0)].append(Piece(PieceType.BEETLE, Player.BLACK))

        assert board == {(0, 0): [Piece(PieceType.ANT, Player.WHITE)]}
