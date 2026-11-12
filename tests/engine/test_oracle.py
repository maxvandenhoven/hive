"""Differential tests: the Rust core plays exactly like the frozen Python engine (D32).

Random games are played on both engines at once. At every ply the two must agree on
everything the rules decide: the legal moves in their order, the end of the game, which
pieces may move and where, placements, articulation points, and the reasons and messages
for illegal moves. Random boards must be accepted or rejected alike by `from_board`. A
failure shrinks to a short game or a small board.
"""

import random
from dataclasses import dataclass

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from oracle.rules import Rules as OracleRules
from oracle.state import GameState as OracleState
from oracle.state import Move as OracleMove

from hive.engine.errors import HiveError
from hive.engine.grid import Coordinate, get_neighbors
from hive.engine.rules import BASE_PIECE_COUNTS, Rules
from hive.engine.state import GameState, Move, Piece, PieceType, Player

type MoveTuple = tuple[PieceType, Coordinate | None, Coordinate] | None

VARIANTS: list[dict[str, object]] = [
    {},
    {"move_before_queen": True},
    {"queen_by_turn": None, "allow_queen_first_turn": False},
    {"starting_player": Player.BLACK, "queen_by_turn": 2},
    {"max_turns": 15},
    {"piece_counts": {PieceType.QUEEN: 1, PieceType.BEETLE: 3, PieceType.ANT: 2}},
]
"""Rule configurations, each built for both engines."""


@dataclass(frozen=True, slots=True)
class Profile:
    """How many games of which length a test plays."""

    settings: settings
    max_plies: int


FAST = Profile(settings=settings(max_examples=40, deadline=None), max_plies=60)
SLOW = Profile(settings=settings(max_examples=300, deadline=None), max_plies=200)
PROFILES = [
    pytest.param(FAST, id="fast"),
    pytest.param(SLOW, id="slow", marks=pytest.mark.slow),
]


def as_tuple(move: Move | OracleMove | None) -> MoveTuple:
    """Write a move of either engine as plain values."""
    if move is None:
        return None

    return (move.piece_type, move.source_coord, move.target_coord)


def candidate_moves(state: OracleState) -> list[MoveTuple]:
    """Build moves to ask both engines about: legal ones and many illegal ones."""
    occupied = sorted(state.board)
    near = sorted({(0, 0), *(n for coord in occupied for n in get_neighbors(coord))})
    candidates: list[MoveTuple] = [None]

    for piece_type in PieceType:
        candidates += [(piece_type, None, target) for target in near[:4]]

    for source in occupied:
        candidates += [(piece_type, source, near[0]) for piece_type in PieceType]
        candidates += [(PieceType.BEETLE, source, target) for target in near[-2:]]

    return candidates


def rust_move(move: MoveTuple) -> Move | None:
    """Build a move of the Rust core from plain values."""
    return None if move is None else Move(*move)


def oracle_move(move: MoveTuple) -> OracleMove | None:
    """Build a move of the oracle from plain values."""
    return None if move is None else OracleMove(*move)


def assert_same_position(
    rules: Rules, oracle: OracleRules, state: GameState, oracle_state: OracleState
) -> None:
    """Assert that both engines describe and judge a position the same way."""
    assert state.board == oracle_state.board
    assert state.hand == oracle_state.hand
    assert state.queen_coord == oracle_state.queen_coord
    assert state.current_player is oracle_state.current_player
    assert state.current_ply == oracle_state.current_ply

    assert [as_tuple(m) for m in rules.legal_moves(state)] == [
        as_tuple(m) for m in oracle.legal_moves(oracle_state)
    ]
    assert rules.winners(state) == oracle.winners(oracle_state)
    assert set(rules.placeable_coords(state)) == set(
        oracle.placeable_coords(oracle_state)
    )
    assert rules.placeable_piece_types(state) == sorted(
        oracle.placeable_piece_types(oracle_state)
    )
    assert set(rules.movable_pieces(state)) == set(oracle.movable_pieces(oracle_state))
    assert state.get_articulation_points() == oracle_state.get_articulation_points()

    for coord in list(oracle_state.board):
        assert set(rules.target_coords(state=state, coord=coord)) == set(
            oracle.target_coords(state=oracle_state, coord=coord)
        )
        assert rules.immobility_reason(
            state=state, coord=coord
        ) == oracle.immobility_reason(state=oracle_state, coord=coord)

    for move in candidate_moves(oracle_state):
        assert rules.illegal_move_reason(
            state=state, move=rust_move(move)
        ) == oracle.illegal_move_reason(state=oracle_state, move=oracle_move(move))


def assert_same_checked_move(
    rules: Rules, oracle: OracleRules, state: GameState, oracle_state: OracleState
) -> None:
    """Assert that both engines reject the same illegal moves with the same message."""
    legal = {as_tuple(m) for m in oracle.legal_moves(oracle_state)}

    for move in candidate_moves(oracle_state):
        if move in legal:
            continue

        with pytest.raises(HiveError) as rust_error:
            rules.apply_checked_move(state=state.copy(), move=rust_move(move))

        with pytest.raises(HiveError) as oracle_error:
            oracle.apply_checked_move(state=oracle_state, move=oracle_move(move))

        assert str(rust_error.value) == str(oracle_error.value)


@pytest.mark.parametrize("profile", PROFILES)
def test_random_games_agree(profile: Profile) -> None:
    """Test that both engines agree at every ply of random games."""

    @profile.settings
    @given(
        variant=st.sampled_from(VARIANTS),
        plies=st.integers(min_value=0, max_value=profile.max_plies),
        seed=st.integers(min_value=0, max_value=2**32),
    )
    def play(variant: dict[str, object], plies: int, seed: int) -> None:
        rules = Rules(**variant)  # ty: ignore[invalid-argument-type]
        oracle = OracleRules(**variant)  # ty: ignore[invalid-argument-type]
        state = rules.create_initial_state()
        oracle_state = oracle.create_initial_state()
        rng = random.Random(seed)

        for ply in range(plies):
            assert_same_position(
                rules=rules, oracle=oracle, state=state, oracle_state=oracle_state
            )

            if ply % 10 == 0:
                assert_same_checked_move(
                    rules=rules, oracle=oracle, state=state, oracle_state=oracle_state
                )
                rebuilt = rules.from_board(
                    board=oracle_state.board,
                    current_player=oracle_state.current_player,
                    current_ply=oracle_state.current_ply,
                )
                assert rebuilt == state

            if rules.is_finished(state):
                break

            legal = oracle.legal_moves(oracle_state)
            move = as_tuple(legal[rng.randrange(len(legal))])
            rules.apply_checked_move(state=state, move=rust_move(move))
            oracle_state.apply_move(oracle_move(move))

    play()


@st.composite
def board_strategy(draw: st.DrawFn) -> dict[Coordinate, list[Piece]]:
    """Draw a small board near the origin, often invalid (disconnected, too full)."""
    coords = draw(
        st.lists(
            st.tuples(st.integers(-2, 2), st.integers(-2, 2)), max_size=8, unique=True
        )
    )
    pieces = st.builds(
        Piece, type=st.sampled_from(PieceType), owner=st.sampled_from(Player)
    )
    return {coord: draw(st.lists(pieces, max_size=3)) for coord in coords}


@settings(max_examples=300, deadline=None)
@given(
    board=board_strategy(),
    current_player=st.sampled_from(Player),
    current_ply=st.none() | st.integers(-1, 20),
)
def test_from_board_agrees(
    board: dict[Coordinate, list[Piece]], current_player: Player, current_ply: int | None
) -> None:
    """Test that both engines accept the same boards, or reject them with one message."""
    rules = Rules(piece_counts=BASE_PIECE_COUNTS)
    oracle = OracleRules()

    try:
        oracle_state = oracle.from_board(
            board=board, current_player=current_player, current_ply=current_ply
        )
    except HiveError as error:
        with pytest.raises(type(error)) as rust_error:
            rules.from_board(
                board=board, current_player=current_player, current_ply=current_ply
            )

        assert str(rust_error.value) == str(error)
        return

    state = rules.from_board(
        board=board, current_player=current_player, current_ply=current_ply
    )
    assert_same_position(
        rules=rules, oracle=oracle, state=state, oracle_state=oracle_state
    )
