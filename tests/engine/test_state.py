from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from hive.engine.state import SHARED_PIECES, GameState, Move, Piece, PieceType, Player


def assert_state_equal(state: GameState, expected: GameState) -> None:
    """Assert that two GameState instances are equal in all properties."""
    assert state.board == expected.board
    assert state.current_player == expected.current_player
    assert state.current_ply == expected.current_ply
    assert state.hand == expected.hand
    assert state.queen_coord == expected.queen_coord


def test_piece_frozen() -> None:
    """Test that piece fields cannot be reassigned."""
    piece = Piece(type=PieceType.ANT, owner=Player.WHITE)

    with pytest.raises(FrozenInstanceError):
        piece.owner = Player.BLACK  # ty: ignore[invalid-assignment]


def test_player_opponent() -> None:
    """Test that the opponent function returns the correct player."""
    assert Player.WHITE.opponent is Player.BLACK
    assert Player.BLACK.opponent is Player.WHITE


class TestGameStateInitialization:
    """Test initialization of the GameState class."""

    def test_initial_state_no_pieces(self) -> None:
        """Test that the initial state has the correct properties."""
        state = GameState(piece_type_count={}, starting_player=Player.WHITE)

        assert state.board == {}
        assert state.current_player is Player.WHITE
        assert state.current_ply == 0
        assert set(state.hand.keys()) == {Player.WHITE, Player.BLACK}
        assert state.hand[Player.WHITE] == {}
        assert state.hand[Player.BLACK] == {}
        assert set(state.queen_coord.keys()) == {Player.WHITE, Player.BLACK}
        assert state.queen_coord[Player.WHITE] is None
        assert state.queen_coord[Player.BLACK] is None

    def test_initial_state_standard_pieces(
        self, default_piece_type_count: dict[PieceType, int]
    ) -> None:
        """Test that the initial state with standard pieces has the correct hands."""
        state = GameState(piece_type_count=default_piece_type_count)

        assert set(state.hand.keys()) == {Player.WHITE, Player.BLACK}
        assert state.hand[Player.WHITE] == default_piece_type_count
        assert state.hand[Player.BLACK] == default_piece_type_count


class TestGameStateMovementAndPlacement:
    """Test placement and movement application and undo behavior."""

    def test_apply_placement_non_queen(self, default_state: GameState) -> None:
        """Test placement application of a non-queen piece."""
        state = default_state
        ant_count_before = state.hand[Player.WHITE][PieceType.ANT]
        move = Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))

        state.apply_placement(move)

        assert set(state.board.keys()) == {(0, 0)}
        assert len(state.board[(0, 0)]) == 1
        assert state.board[(0, 0)][0].type is PieceType.ANT
        assert state.board[(0, 0)][0].owner is state.current_player
        assert state.hand[Player.WHITE][PieceType.ANT] == ant_count_before - 1
        assert state.queen_coord[Player.WHITE] is None

    def test_apply_placement_queen(self, default_state: GameState) -> None:
        """Test placement of a queen piece updates queen location."""
        state = default_state
        queen_count_before = state.hand[Player.WHITE][PieceType.QUEEN]
        move = Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0))

        state.apply_placement(move)

        assert set(state.board.keys()) == {(0, 0)}
        assert len(state.board[(0, 0)]) == 1
        assert state.board[(0, 0)][0].type is PieceType.QUEEN
        assert state.board[(0, 0)][0].owner is state.current_player
        assert state.hand[Player.WHITE][PieceType.QUEEN] == queen_count_before - 1
        assert state.queen_coord[Player.WHITE] == (0, 0)

    def test_apply_placement_shares_pieces(self, default_state: GameState) -> None:
        """Test that placements put the shared instance of the piece on the board."""
        state = default_state
        move = Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))

        state.apply_placement(move)

        assert state.board[(0, 0)][0] is SHARED_PIECES[Player.WHITE, PieceType.ANT]
        assert SHARED_PIECES[Player.BLACK, PieceType.QUEEN] == Piece(
            type=PieceType.QUEEN, owner=Player.BLACK
        )

    def test_undo_placement_non_queen(self, default_state: GameState) -> None:
        """Test undoing non-queen placement restores board and hand."""
        state = deepcopy(default_state)
        expected = deepcopy(default_state)
        move = Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(0, 0))

        state.apply_placement(move)
        state.undo_placement(move)

        assert_state_equal(state=state, expected=expected)

    def test_undo_placement_queen(self, default_state: GameState) -> None:
        """Test undoing queen placement also resets queen location."""
        state = deepcopy(default_state)
        expected = deepcopy(default_state)
        move = Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 1))

        state.apply_placement(move)
        state.undo_placement(move)

        assert_state_equal(state=state, expected=expected)
        assert state.queen_coord[Player.WHITE] is None

    def test_apply_movement_non_queen(self, default_state: GameState) -> None:
        """Test movement of a non-queen piece removes source and populates target."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        ant_count_before = state.hand[Player.WHITE][PieceType.ANT]
        move = Move(piece_type=PieceType.ANT, source_coord=(0, 0), target_coord=(1, 0))

        state.apply_movement(move)

        assert (0, 0) not in state.board
        assert set(state.board.keys()) == {(1, 0)}
        assert len(state.board[(1, 0)]) == 1
        assert state.board[(1, 0)][0].type is PieceType.ANT
        assert state.board[(1, 0)][0].owner is state.current_player
        assert state.hand[Player.WHITE][PieceType.ANT] == ant_count_before
        assert state.queen_coord[Player.WHITE] is None

    def test_apply_movement_queen(self, default_state: GameState) -> None:
        """Test movement of a queen piece updates its tracked coordinate."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0))
        )
        queen_count_before = state.hand[Player.WHITE][PieceType.QUEEN]
        move = Move(piece_type=PieceType.QUEEN, source_coord=(0, 0), target_coord=(1, -1))

        state.apply_movement(move)

        assert (0, 0) not in state.board
        assert set(state.board.keys()) == {(1, -1)}
        assert len(state.board[(1, -1)]) == 1
        assert state.board[(1, -1)][0].type is PieceType.QUEEN
        assert state.board[(1, -1)][0].owner is state.current_player
        assert state.hand[Player.WHITE][PieceType.QUEEN] == queen_count_before
        assert state.queen_coord[Player.WHITE] == (1, -1)

    def test_apply_movement_from_stack(self, default_state: GameState) -> None:
        """Test movement from a stack pops only the top piece."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        state.apply_placement(
            Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(0, 0))
        )
        move = Move(piece_type=PieceType.BEETLE, source_coord=(0, 0), target_coord=(0, 1))

        state.apply_movement(move)

        assert len(state.board[(0, 0)]) == 1
        assert state.board[(0, 0)][-1].type is PieceType.ANT
        assert len(state.board[(0, 1)]) == 1
        assert state.board[(0, 1)][-1].type is PieceType.BEETLE
        assert state.board[(0, 1)][-1].owner is Player.WHITE

    def test_apply_movement_onto_occupied(self, default_state: GameState) -> None:
        """Test movement onto an occupied coordinate stacks the piece on top."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        state.apply_placement(
            Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(1, 0))
        )
        move = Move(piece_type=PieceType.BEETLE, source_coord=(1, 0), target_coord=(0, 0))

        state.apply_movement(move)

        assert (1, 0) not in state.board
        assert len(state.board[(0, 0)]) == 2
        assert state.board[(0, 0)][0].type is PieceType.ANT
        assert state.board[(0, 0)][1].type is PieceType.BEETLE

    def test_apply_movement_raises_without_source(self, default_state: GameState) -> None:
        """Test movement raises ValueError when source coordinate is None."""
        state = default_state
        move = Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))

        with pytest.raises(ValueError):
            state.apply_movement(move)

    def test_undo_movement_non_queen(self, default_state: GameState) -> None:
        """Test undoing non-queen movement restores board state."""
        state = deepcopy(default_state)
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        expected = deepcopy(state)
        move = Move(piece_type=PieceType.ANT, source_coord=(0, 0), target_coord=(1, 0))

        state.apply_movement(move)
        state.undo_movement(move)

        assert_state_equal(state=state, expected=expected)

    def test_undo_movement_queen(self, default_state: GameState) -> None:
        """Test undoing queen movement restores board and queen coordinate."""
        state = deepcopy(default_state)
        state.apply_placement(
            Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0))
        )
        expected = deepcopy(state)
        move = Move(piece_type=PieceType.QUEEN, source_coord=(0, 0), target_coord=(1, 0))

        state.apply_movement(move)
        state.undo_movement(move)

        assert_state_equal(state=state, expected=expected)

    def test_undo_movement_from_stack(self, default_state: GameState) -> None:
        """Test undoing movement from a stack restores the original stack order."""
        state = deepcopy(default_state)
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        state.apply_placement(
            Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(0, 0))
        )
        expected = deepcopy(state)
        move = Move(piece_type=PieceType.BEETLE, source_coord=(0, 0), target_coord=(0, 1))

        state.apply_movement(move)
        state.undo_movement(move)

        assert_state_equal(state=state, expected=expected)

    def test_undo_movement_onto_occupied(self, default_state: GameState) -> None:
        """Test undoing movement onto an occupied target restores both stacks."""
        state = deepcopy(default_state)
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        state.apply_placement(
            Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(1, 0))
        )
        expected = deepcopy(state)
        move = Move(piece_type=PieceType.BEETLE, source_coord=(1, 0), target_coord=(0, 0))

        state.apply_movement(move)
        state.undo_movement(move)

        assert_state_equal(state=state, expected=expected)

    def test_undo_movement_raises_without_source(self, default_state: GameState) -> None:
        """Test undo movement raises ValueError when source coordinate is None."""
        state = default_state
        move = Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))

        with pytest.raises(ValueError):
            state.undo_movement(move)

    def test_apply_and_undo_pass(self, default_state: GameState) -> None:
        """Test apply/undo for pass move only changes turn and ply."""
        state = deepcopy(default_state)
        expected = deepcopy(default_state)

        state.apply_move(None)

        assert state.current_ply == 1
        assert state.current_player is Player.BLACK
        assert state.board == expected.board

        state.undo_move(None)

        assert_state_equal(state=state, expected=expected)

    def test_apply_and_undo_placement(self, default_state: GameState) -> None:
        """Test `apply_move`/`undo_move` with source None uses placement handlers."""
        state = deepcopy(default_state)
        expected = deepcopy(default_state)
        move = Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0))

        state.apply_move(move)

        assert state.current_ply == 1
        assert state.current_player is Player.BLACK
        assert state.board[(0, 0)][-1].type is PieceType.QUEEN

        state.undo_move(move)

        assert_state_equal(state=state, expected=expected)

    def test_apply_and_undo_movement(self, default_state: GameState) -> None:
        """Test `apply_move`/`undo_move` with source coordinate uses movement handlers."""
        state = deepcopy(default_state)
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        expected = deepcopy(state)
        move = Move(piece_type=PieceType.ANT, source_coord=(0, 0), target_coord=(1, 0))

        state.apply_move(move)

        assert state.current_ply == 1
        assert state.current_player is Player.BLACK
        assert (0, 0) not in state.board
        assert state.board[(1, 0)][-1].type is PieceType.ANT

        state.undo_move(move)

        assert_state_equal(state=state, expected=expected)


class TestGameStateIsOccupied:
    """Test the `is_occupied` board query."""

    def test_empty_board(self, default_state: GameState) -> None:
        """Test that an empty board has no occupied coordinates."""
        state = default_state
        assert not state.is_occupied((0, 0))

    def test_occupied_after_placement(self, default_state: GameState) -> None:
        """Test that a coordinate is occupied after placing a piece."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        assert state.is_occupied((0, 0))


class TestGameStateIsSurrounded:
    """Test the `is_surrounded` neighbor check."""

    def test_not_surrounded_single_piece(self, default_state: GameState) -> None:
        """Test that a lone piece is not surrounded."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0))
        )
        assert not state.is_surrounded((0, 0))

    def test_surrounded_by_six_neighbors(self, ring_6_state: GameState) -> None:
        """Test that all six neighbors occupied means surrounded."""
        state = ring_6_state
        assert state.is_surrounded((0, 0))


class TestGameStateCountOccupiedNeighbors:
    """Test the `count_occupied_neighbors` count."""

    def test_no_neighbors(self, default_state: GameState) -> None:
        """Test that an empty board has no occupied neighbors."""
        assert default_state.count_occupied_neighbors((0, 0)) == 0

    def test_line(self, line_3_state: GameState) -> None:
        """Test the counts along a line, where a stack counts once."""
        state = line_3_state
        state.apply_placement(
            Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(1, 0))
        )

        assert state.count_occupied_neighbors((0, 0)) == 2
        assert state.count_occupied_neighbors((1, 0)) == 1
        assert state.count_occupied_neighbors((0, 1)) == 2

    def test_ring(self, ring_6_state: GameState) -> None:
        """Test that the center of a ring has six occupied neighbors."""
        assert ring_6_state.count_occupied_neighbors((0, 0)) == 6


class TestGameStateGetQueenCoord:
    """Test the `get_queen_coord` query."""

    def test_returns_coord_after_placement(self, default_state: GameState) -> None:
        """Test that queen coordinate is set after placement."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(2, 3))
        )
        assert state.get_queen_coord(Player.WHITE) == (2, 3)


class TestGameStateGetTopPiece:
    """Test the `get_top_piece` query."""

    def test_single_piece(self, default_state: GameState) -> None:
        """Test top piece on a coordinate with one piece."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )

        top = state.get_top_piece((0, 0))
        assert top.type is PieceType.ANT
        assert top.owner is Player.WHITE

    def test_stacked_pieces(self, default_state: GameState) -> None:
        """Test top piece returns the last piece placed on a stack."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        state.apply_placement(
            Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(0, 0))
        )

        top = state.get_top_piece((0, 0))
        assert top.type is PieceType.BEETLE


class TestGameStateGetStackHeight:
    """Test the `get_stack_height` query."""

    def test_single_piece(self, default_state: GameState) -> None:
        """Test stack height is one for a single piece."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        assert state.get_stack_height((0, 0)) == 1

    def test_stacked_pieces(self, default_state: GameState) -> None:
        """Test stack height reflects the number of pieces."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        state.apply_placement(
            Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(0, 0))
        )
        assert state.get_stack_height((0, 0)) == 2


class TestGameStateGetOccupiedCoords:
    """Test the `get_occupied_coords` query."""

    def test_empty_board(self, default_state: GameState) -> None:
        """Test that an empty board returns no coordinates."""
        state = default_state
        assert state.get_occupied_coords() == set()

    def test_single_piece(self, default_state: GameState) -> None:
        """Test occupied coords with one piece on the board."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        assert state.get_occupied_coords() == {(0, 0)}

    def test_multiple_pieces(self, default_state: GameState) -> None:
        """Test occupied coords with pieces on different coordinates."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        state.apply_placement(
            Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(1, 0))
        )
        assert state.get_occupied_coords() == {(0, 0), (1, 0)}

    def test_stacked_pieces_count_once(self, default_state: GameState) -> None:
        """Test that a stack on one coordinate appears as a single entry."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        state.apply_placement(
            Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(0, 0))
        )
        assert state.get_occupied_coords() == {(0, 0)}


class TestGameStateGetAdjacentPlayers:
    """Test the `get_adjacent_players` query."""

    def test_no_neighbors(self, default_state: GameState) -> None:
        """Test that an isolated coordinate has no adjacent players."""
        state = default_state
        assert state.get_adjacent_players((0, 0)) == set()

    def test_single_player_neighbor(self, default_state: GameState) -> None:
        """Test adjacent players with one neighboring piece."""
        state = default_state
        state.board[(1, 0)] = [Piece(type=PieceType.ANT, owner=Player.WHITE)]
        assert state.get_adjacent_players((0, 0)) == {Player.WHITE}

    def test_both_players_adjacent(self, default_state: GameState) -> None:
        """Test adjacent players with neighbors from both players."""
        state = default_state
        state.board[(1, 0)] = [Piece(type=PieceType.ANT, owner=Player.WHITE)]
        state.board[(-1, 0)] = [Piece(type=PieceType.ANT, owner=Player.BLACK)]
        assert state.get_adjacent_players((0, 0)) == {Player.WHITE, Player.BLACK}

    def test_uses_top_piece_owner(self, default_state: GameState) -> None:
        """Test that stacked pieces report the top piece's owner."""
        state = default_state
        state.board[(1, 0)] = [
            Piece(type=PieceType.ANT, owner=Player.WHITE),
            Piece(type=PieceType.BEETLE, owner=Player.BLACK),
        ]
        assert state.get_adjacent_players((0, 0)) == {Player.BLACK}


class TestCalculateBoundaryCoords:
    """Test the `calculate_boundary_coords` internal helper."""

    def test_empty_board(self, default_state: GameState) -> None:
        """Test that an empty board has no boundary coordinates."""
        state = default_state
        assert state.calculate_boundary_coords() == set()

    def test_single_piece(self, default_state: GameState) -> None:
        """Test that a single piece yields its six neighbors as boundary."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )

        boundary = state.calculate_boundary_coords()
        assert boundary == {(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)}

    def test_two_adjacent_pieces(self, default_state: GameState) -> None:
        """Test boundary for two adjacent pieces shares no occupied coords."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(1, 0))
        )

        boundary = state.calculate_boundary_coords()
        assert (0, 0) not in boundary
        assert (1, 0) not in boundary
        assert len(boundary) == 8

    def test_ring_has_inner_and_outer_boundary(self, ring_6_state: GameState) -> None:
        """Test that a ring of six pieces has both inner and outer boundary."""
        state = ring_6_state

        boundary = state.calculate_boundary_coords()
        assert (0, 0) in boundary
        assert len(boundary) == 13

    def test_stacked_pieces_same_boundary(self, default_state: GameState) -> None:
        """Test that a stack produces the same boundary as a single piece."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        state.apply_placement(
            Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(0, 0))
        )

        boundary = state.calculate_boundary_coords()
        assert boundary == {(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)}


class TestPieceLifted:
    """Test the `piece_lifted` context manager."""

    def test_removes_single_piece_from_board(self, default_state: GameState) -> None:
        """Test that lifting the only piece removes the coord from the board."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )

        with state.piece_lifted((0, 0)):
            assert not state.is_occupied((0, 0))

    def test_restores_single_piece_after_exit(self, default_state: GameState) -> None:
        """Test that the piece is restored after the context exits."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.SPIDER, source_coord=None, target_coord=(0, 0))
        )

        with state.piece_lifted((0, 0)):
            pass

        assert state.is_occupied((0, 0))
        assert state.get_top_piece((0, 0)).type is PieceType.SPIDER

    def test_yields_the_lifted_piece(self, default_state: GameState) -> None:
        """Test that the context manager yields the correct piece."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0))
        )

        with state.piece_lifted((0, 0)) as piece:
            assert piece.type is PieceType.QUEEN
            assert piece.owner is Player.WHITE

    def test_lifts_top_from_stack(self, default_state: GameState) -> None:
        """Test that only the top piece is lifted from a stack."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        state.apply_placement(
            Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(0, 0))
        )

        with state.piece_lifted((0, 0)) as piece:
            assert piece.type is PieceType.BEETLE
            assert state.is_occupied((0, 0))
            assert state.get_top_piece((0, 0)).type is PieceType.ANT

    def test_restores_stack_after_exit(self, default_state: GameState) -> None:
        """Test that the stack is fully restored after context exit."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        state.apply_placement(
            Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(0, 0))
        )

        with state.piece_lifted((0, 0)):
            pass

        assert state.get_stack_height((0, 0)) == 2
        assert state.get_top_piece((0, 0)).type is PieceType.BEETLE

    def test_restores_piece_on_exception(self, default_state: GameState) -> None:
        """Test that the piece is restored even if the body raises."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )

        with pytest.raises(RuntimeError):
            with state.piece_lifted((0, 0)):
                msg = "boom"
                raise RuntimeError(msg)

        assert state.is_occupied((0, 0))
        assert state.get_stack_height((0, 0)) == 1


class TestGetArticulationPoints:
    """Test the `get_articulation_points` Tarjan implementation."""

    def test_empty_board(self, default_state: GameState) -> None:
        """Test that an empty board has no articulation points."""
        state = default_state
        assert state.get_articulation_points() == set()

    def test_single_piece(self, default_state: GameState) -> None:
        """Test that a single piece has no articulation points."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0))
        )
        assert state.get_articulation_points() == set()

    def test_two_pieces(self, default_state: GameState) -> None:
        """Test that two adjacent pieces have no articulation points."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(1, 0))
        )
        assert state.get_articulation_points() == set()

    def test_line_of_three(self, line_3_state: GameState) -> None:
        """Test that the center of a three-piece line is an articulation point."""
        state = line_3_state
        assert state.get_articulation_points() == {(0, 0)}

    def test_ring_no_articulation_points(self, ring_6_state: GameState) -> None:
        """Test that a six-piece ring has no articulation points."""
        state = ring_6_state
        assert state.get_articulation_points() == set()

    def test_t_shape(self, t_shape_state: GameState) -> None:
        """Test that the junction of a T-shape is an articulation point."""
        state = t_shape_state
        assert state.get_articulation_points() == {(0, 0)}

    def test_l_shape(self, l_shape_state: GameState) -> None:
        """Test articulation points in an L-shaped layout."""
        state = l_shape_state
        assert state.get_articulation_points() == {(0, 0), (1, 0)}

    def test_stacked_piece_excluded(self, line_3_state: GameState) -> None:
        """Test that a stacked articulation point is excluded."""
        state = line_3_state
        state.apply_placement(
            Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(0, 0))
        )
        assert state.get_articulation_points() == set()

    def test_long_chain(self, long_chain_state: GameState) -> None:
        """Test that all interior pieces in a five-piece chain are flagged."""
        state = long_chain_state
        assert state.get_articulation_points() == {(-1, 0), (0, 0), (1, 0)}


class TestIsConnected:
    """Test the `is_connected` DFS connectivity check."""

    def test_empty_board(self, default_state: GameState) -> None:
        """Test that an empty board counts as connected."""
        assert default_state.is_connected()

    def test_connected_layouts(
        self, line_3_state: GameState, ring_6_state: GameState
    ) -> None:
        """Test that a line and a ring are connected."""
        assert line_3_state.is_connected()
        assert ring_6_state.is_connected()

    def test_split_board(self, line_3_state: GameState) -> None:
        """Test that a board with two separate groups is not connected."""
        state = line_3_state

        with state.piece_lifted((0, 0)):
            assert not state.is_connected()


class TestIsConnectedAfterRemoving:
    """Test the `is_connected_after_removing` DFS connectivity check."""

    def test_removing_endpoint_stays_connected(self, line_3_state: GameState) -> None:
        """Test that removing an endpoint keeps the board connected."""
        state = line_3_state
        assert state.is_connected_after_removing((-1, 0))
        assert state.is_connected_after_removing((1, 0))

    def test_removing_center_disconnects(self, line_3_state: GameState) -> None:
        """Test that removing the center of a line disconnects the board."""
        state = line_3_state
        assert not state.is_connected_after_removing((0, 0))

    def test_ring_stays_connected(self, ring_6_state: GameState) -> None:
        """Test that removing any piece from a ring keeps it connected."""
        state = ring_6_state

        for coord in state.get_occupied_coords():
            assert state.is_connected_after_removing(coord)

    def test_stacked_piece_always_connected(self, line_3_state: GameState) -> None:
        """Test that removing from a stack always stays connected."""
        state = line_3_state
        state.apply_placement(
            Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(0, 0))
        )
        assert state.is_connected_after_removing((0, 0))

    def test_t_shape_junction_disconnects(self, t_shape_state: GameState) -> None:
        """Test that removing the T-shape junction disconnects the board."""
        state = t_shape_state
        assert not state.is_connected_after_removing((0, 0))

    def test_agrees_with_articulation_points(self, l_shape_state: GameState) -> None:
        """Test that articulation points match `is_connected_after_removing`."""
        state = l_shape_state
        articulation_points = state.get_articulation_points()

        for coord in state.get_occupied_coords():
            if coord in articulation_points:
                assert not state.is_connected_after_removing(coord)
            else:
                assert state.is_connected_after_removing(coord)


class TestCanSlide:
    """Test the `can_slide` gate-check for piece movement.

    Coordinate reference for sliding from (0,0) east to (1,0):
      - Direction: (1, 0)
      - Anti-clockwise flank: (1, -1) (north-east)
      - Clockwise flank: (0, 1) (south-east)
    The slide is blocked only when both flanks are occupied.
    """

    def test_slide_to_empty_unblocked(self, default_state: GameState) -> None:
        """Test sliding to an empty target with no flanking pieces."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        assert state.can_slide(source_coord=(0, 0), target_coord=(1, 0))

    def test_blocked_when_target_occupied(self, default_state: GameState) -> None:
        """Test that sliding into an occupied target is blocked."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(1, 0))
        )
        assert not state.can_slide(source_coord=(0, 0), target_coord=(1, 0))

    def test_blocked_when_both_flanks_occupied(self, east_gate_state: GameState) -> None:
        """Test that two occupied flanks block the slide (gate)."""
        state = east_gate_state
        assert not state.can_slide(source_coord=(0, 0), target_coord=(1, 0))

    def test_one_flank_occupied_still_slides(self, default_state: GameState) -> None:
        """Test that a single occupied flank does not block the slide."""
        state = default_state
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))
        )
        state.apply_placement(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(1, -1))
        )
        assert state.can_slide(source_coord=(0, 0), target_coord=(1, 0))


@pytest.mark.parametrize(
    ("move", "description"),
    [
        (
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(1, 0)),
            "place ant at (1, 0)",
        ),
        (
            Move(piece_type=PieceType.BEETLE, source_coord=(0, 0), target_coord=(0, -1)),
            "move beetle from (0, 0) to (0, -1)",
        ),
    ],
)
def test_move_str(move: Move, description: str) -> None:
    """Test that a move describes itself as a placement or a movement."""
    assert str(move) == description
