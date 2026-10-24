from hive.agents.evaluators.mobility import MobilityEvaluator
from hive.engine.rules import Rules
from hive.engine.state import Move, PieceType, Player


def test_passing_player_has_no_mobility() -> None:
    """Test that moves are counted exactly and a forced pass counts as zero moves."""
    rules = Rules()
    state = rules.create_initial_state()
    placements = [
        (Player.WHITE, PieceType.QUEEN, (0, 0)),
        (Player.BLACK, PieceType.QUEEN, (1, 0)),
        (Player.WHITE, PieceType.ANT, (-1, 0)),
        (Player.BLACK, PieceType.BEETLE, (-1, 0)),
    ]
    for owner, piece_type, coord in placements:
        state.current_player = owner
        state.apply_placement(
            Move(piece_type=piece_type, source_coord=None, target_coord=coord)
        )
    state.current_ply = 4

    state.current_player = Player.BLACK
    black_move_count = len(rules.legal_moves(state))
    state.current_player = Player.WHITE

    assert rules.legal_moves(state) == [None]
    assert MobilityEvaluator(rules).evaluate(state, Player.WHITE) == -black_move_count
    assert state.current_player is Player.WHITE
