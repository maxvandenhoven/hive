"""Property tests for the unchecked fast path `apply_move` and `undo_move`.

Random games are drawn with `hypothesis`, so a failure shrinks to a short game. The fast
settings run in `make test`; the slow settings play more and longer games.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hive.engine.grid import Coordinate
from hive.engine.rules import Rules
from hive.engine.state import GameState, Move, Piece, PieceType, Player

type Game = tuple[Rules, list[Move | None]]
type Snapshot = tuple[
    dict[Coordinate, list[Piece]],
    Player,
    int,
    dict[Player, dict[PieceType, int]],
    dict[Player, Coordinate | None],
]

RULES = [
    Rules(),
    Rules(move_before_queen=True),
    Rules(queen_by_turn=None, allow_queen_first_turn=False),
    Rules(starting_player=Player.BLACK, queen_by_turn=2),
]


@dataclass(frozen=True, slots=True)
class Profile:
    settings: settings
    max_plies: int


FAST = Profile(settings=settings(max_examples=100, deadline=None), max_plies=100)
SLOW = Profile(settings=settings(max_examples=500, deadline=None), max_plies=300)
PROFILES = [
    pytest.param(FAST, id="fast"),
    pytest.param(SLOW, id="slow", marks=pytest.mark.slow),
]


@st.composite
def game_strategy(draw: st.DrawFn, max_plies: int) -> Game:
    """Draw rules and a random sequence of legal moves, stopping when the game ends."""
    rules = draw(st.sampled_from(RULES))
    plies = draw(st.integers(min_value=0, max_value=max_plies))

    state = rules.create_initial_state()
    moves: list[Move | None] = []

    while len(moves) < plies and not rules.is_finished(state):
        move = draw(st.sampled_from(rules.legal_moves(state)))
        state.apply_move(move)
        moves.append(move)

    return rules, moves


def snapshot(state: GameState) -> Snapshot:
    """Copy every field of the state into plain values for comparison."""
    return (
        {coord: list(stack) for coord, stack in state.board.items()},
        state.current_player,
        state.current_ply,
        {player: dict(hand) for player, hand in state.hand.items()},
        dict(state.queen_coord),
    )


def assert_invariants(state: GameState, rules: Rules) -> None:
    """Assert that the state satisfies invariants 1 to 5 from `engine.md`."""
    # 1. Every board key maps to a non-empty stack.
    assert all(state.board.values())

    # 2. The occupied coordinates form one connected hive.
    assert state.is_connected()

    # 3. Pieces on the board plus pieces in hand equal the piece counts.
    on_board = Counter(
        (piece.owner, piece.type) for stack in state.board.values() for piece in stack
    )

    for player in Player:
        for piece_type, count in rules.piece_counts.items():
            in_hand = state.hand[player].get(piece_type, 0)
            assert in_hand >= 0
            assert on_board[player, piece_type] + in_hand == count

    # 4. The queen coordinates point at each player's queen, or `None` if not placed.
    for player in Player:
        queen_coords = [
            coord
            for coord, stack in state.board.items()
            for piece in stack
            if piece.owner is player and piece.type is PieceType.QUEEN
        ]
        assert state.queen_coord[player] == (queen_coords[0] if queen_coords else None)

    # 5. The current player alternates every ply, starting with the starting player.
    expected_player = (
        rules.starting_player
        if state.current_ply % 2 == 0
        else rules.starting_player.opponent
    )
    assert state.current_player is expected_player


def run_profile(profile: Profile, check: Callable[[Game], None]) -> None:
    """Run `check` on random games drawn with the settings of `profile`."""
    profile.settings(given(game_strategy(max_plies=profile.max_plies))(check))()


@pytest.mark.parametrize("profile", PROFILES)
def test_undo_restores_state(profile: Profile) -> None:
    """Test that every move keeps the invariants and undoing it restores the state."""

    def check(game: Game) -> None:
        rules, moves = game
        state = rules.create_initial_state()
        assert_invariants(state=state, rules=rules)

        snapshots = [snapshot(state)]

        for move in moves:
            before = snapshot(state)
            state.apply_move(move)
            assert_invariants(state=state, rules=rules)

            state.undo_move(move)
            assert snapshot(state) == before

            state.apply_move(move)
            snapshots.append(snapshot(state))

        # Undoing the whole game walks back through every earlier state.
        for move in reversed(moves):
            snapshots.pop()
            state.undo_move(move)
            assert snapshot(state) == snapshots[-1]

    run_profile(profile=profile, check=check)


@pytest.mark.parametrize("profile", PROFILES)
def test_replay_reproduces_state(profile: Profile) -> None:
    """Test that replaying with `Rules.apply_checked_move` gives the same state."""

    def check(game: Game) -> None:
        rules, moves = game
        fast_state = rules.create_initial_state()

        for move in moves:
            fast_state.apply_move(move)

        replayed_state = rules.create_initial_state()

        for move in moves:
            rules.apply_checked_move(state=replayed_state, move=move)

        assert snapshot(replayed_state) == snapshot(fast_state)

    run_profile(profile=profile, check=check)


@pytest.mark.parametrize("profile", PROFILES)
def test_from_board_reproduces_state(profile: Profile) -> None:
    """Test that `from_board` derives the hands and queen coordinates of every state."""

    def check(game: Game) -> None:
        rules, moves = game
        state = rules.create_initial_state()

        for move in moves:
            state.apply_move(move)

            rebuilt = rules.from_board(
                board=state.board,
                current_player=state.current_player,
                current_ply=state.current_ply,
            )
            assert snapshot(rebuilt) == snapshot(state)

            # The derived ply is the lowest valid one, so it never exceeds the real ply.
            derived = rules.from_board(
                board=state.board, current_player=state.current_player
            )
            assert derived.current_ply <= state.current_ply
            assert_invariants(state=derived, rules=rules)

    run_profile(profile=profile, check=check)


@pytest.mark.parametrize("profile", PROFILES)
def test_articulation_points_match_removal(profile: Profile) -> None:
    """Test that the articulation points are the pieces whose removal splits the hive."""

    def check(game: Game) -> None:
        rules, moves = game
        state = rules.create_initial_state()

        for move in moves:
            state.apply_move(move)

            expected = {
                coord
                for coord in state.board
                if not state.is_connected_after_removing(coord)
            }
            assert state.get_articulation_points() == expected

    run_profile(profile=profile, check=check)
